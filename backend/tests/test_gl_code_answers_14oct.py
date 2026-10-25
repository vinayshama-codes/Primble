"""The GL class code a person gives reaches the forms, and only as a code
(14 Oct 2026, adversarial review of the fix for live run `b117f010`).

1. An answer given AFTER generation re-stamped only boxes whose canonical key
   IS the answered fact. ACORD 125's GL CODE and the 126 hazard grid are
   derived by resolvers, so the card closed and the score counted the code
   while both forms stayed blank (`arq_service._restamp_boxes_the_answer_decides`).
2. Free text printed as a code: a ZIP ("Denver CO 80221"), a payroll, a year,
   an SIC or a NAICS code reached the 125 and the 126
   (`sqs_service.gl_code_tokens_in_text`).
3. An AI-read applicant code beat the person's answer on the 125 while the 126
   printed the answer.
4. WC classes a combined package files under GL printed as 126 hazards, and
   the 125 gave up before reaching the person's code.
"""
import asyncio
import copy
import json
import os
from unittest.mock import AsyncMock, patch

import pytest

import services.arq_service as arq
import services.pdf_service as ps
from services.sqs_service import gl_class_codes_present, gl_code_tokens_in_text

HERE = os.path.dirname(os.path.abspath(__file__))
GL = "NamedInsured_GeneralLiabilityCode_A"
HZ = "GeneralLiability_Hazard_ClassCode_"


def _schema(form_id):
    with open(os.path.join(HERE, "..", "forms_schemas", f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _person(value):
    return {"value": value, "source": "producer"}


def _box(form_id, field, facts):
    with ps._schema_context(_schema(form_id)):
        return ps._deterministic_map(field, {**facts, "_form_id": form_id})


def _printed(value):
    return value not in (None, "", "UNMATCHED")


# ── 1. an answer given after generation ───────────────────────────────────────

def _generated(facts, form_ids=("ACORD_125", "ACORD_126")):
    out = {}
    for fid in form_ids:
        m, c = ps.map_facts_to_form(dict(facts), _schema(fid), fid, "", allow_llm=False)
        out[fid] = {"schema": _schema(fid), "field_state": m, "confidence": c}
    return out


def _answer_after_generation(row, field, value):
    async def _get(_sid):
        return copy.deepcopy(row)

    async def _upd(_sid, payload, **_kw):
        row.update(payload)

    with patch("repositories.session_repository.get_processing_session", _get), \
         patch("repositories.session_repository.upd_processing_session", _upd):
        return asyncio.run(arq.apply_producer_answer_to_session("s1", field, value))


def test_an_answer_after_generation_reaches_the_125_and_the_126():
    facts = {"applicant_name": "Choice Electric LLC", "has_general_liability": True}
    row = {"facts": facts, "flags": {}, "generated_forms": _generated(facts)}
    assert not _printed(row["generated_forms"]["ACORD_125"]["field_state"].get(GL))
    ok, updated = _answer_after_generation(row, "gl_class_codes_by_location", "92478")
    assert ok and {"ACORD_125", "ACORD_126"} <= set(updated)
    f125, f126 = row["generated_forms"]["ACORD_125"], row["generated_forms"]["ACORD_126"]
    assert f125["field_state"][GL] == "92478" and f125["confidence"][GL] == "producer"
    assert f126["field_state"][HZ + "A"] == "92478" and f126["confidence"][HZ + "A"] == "producer"
    assert f126["_pdf_cache_hash"] == "" and f125["pdf_bytes"] is None


def test_the_answer_never_moves_a_box_a_person_typed():
    facts = {"applicant_name": "Choice Electric LLC", "has_general_liability": True}
    row = {"facts": facts, "flags": {}, "generated_forms": _generated(facts)}
    f126 = row["generated_forms"]["ACORD_126"]
    f126["field_state"][HZ + "A"] = "91580"
    f126["confidence"][HZ + "A"] = "producer"
    _answer_after_generation(row, "gl_class_codes_by_location", "92478")
    f126 = row["generated_forms"]["ACORD_126"]
    assert f126["field_state"][HZ + "A"] == "91580" and f126["confidence"][HZ + "A"] == "producer"
    assert row["generated_forms"]["ACORD_125"]["field_state"][GL] == "92478"


def test_a_client_answer_after_generation_reaches_the_derived_boxes_too():
    facts = {"applicant_name": "Choice Electric LLC", "has_general_liability": True}
    session = {"facts": dict(facts), "flags": {}, "generated_forms": _generated(facts)}
    arq_row = {"id": "arq-1", "status": "submitted", "session_id": "s1",
               "answers": {"gl_class_codes_by_location": "92478"},
               "questions": [{"field_name": "gl_class_codes_by_location", "question": "GL class codes?"}]}
    saved: dict = {}

    async def _upd(_sid, payload, delete_facts=None):
        saved.update(payload)

    with patch.object(arq, "get_arq_by_id", AsyncMock(return_value=arq_row)), \
         patch("repositories.session_repository.get_processing_session", AsyncMock(return_value=session)), \
         patch("repositories.session_repository.upd_processing_session", _upd):
        ok, _ = asyncio.run(arq.apply_arq_answers_to_session("arq-1", "s1"))
    assert ok
    forms = saved["generated_forms"]
    assert forms["ACORD_125"]["field_state"][GL] == "92478"
    assert forms["ACORD_126"]["field_state"][HZ + "A"] == "92478"


def test_no_forms_means_nothing_to_restamp():
    assert arq._restamp_boxes_the_answer_decides({}, {}, {"x": 1}, {"x"}, "1", "producer") == []
    assert arq._restamp_boxes_the_answer_decides({"ACORD_125": {}}, {}, {}, set(), None, "producer") == []


# ── 2. free text is read for codes, never for any number ─────────────────────

@pytest.mark.parametrize("typed", [
    "Electrical contracting at 4800 Pecos St, Denver CO 80221",
    "Electrical contractor since 2015",
    "1731", "5190", "238210",
    "Total payroll 39300",
    "Office at 12345 Pecos Street",
])
def test_free_text_never_prints_a_zip_payroll_year_or_other_code(typed):
    f = {"applicant_name": "Choice Electric LLC", "gl_class_codes_by_location": _person(typed)}
    assert not _printed(_box("ACORD_125", GL, f))
    assert [_box("ACORD_126", HZ + L, f) for L in "AB"] == [None, None]


@pytest.mark.parametrize("typed,codes", [
    ("92478 electrical, payroll 39300", ["92478"]),
    ("Loc 1: 92478; Loc 2: 91580", ["92478", "91580"]),
    ("GL class code 92478 (electrical)", ["92478"]),
    ("Electrical 92478 and plumbing 98482", ["92478", "98482"]),
])
def test_real_codes_in_free_text_print_on_both_forms(typed, codes):
    f = {"applicant_name": "Choice Electric LLC", "gl_class_codes_by_location": _person(typed)}
    assert _box("ACORD_125", GL, f) == ", ".join(codes)
    assert [_box("ACORD_126", HZ + L, f) for L in "AB"][:len(codes)] == codes


@pytest.mark.parametrize("text,want", [
    ("80221", ["80221"]), ("CO 80221", []), ("co 80221", []), ("IN 46204", []), ("work in 92478", ["92478"]),
    ("Denver, Colorado 80221", []), ("New York 10001", []), ("$92478", []), ("92478.00", []), ("92,478", []),
    ("80221-1234", []), ("CG 91580", ["91580"]), ("Class: 92478", ["92478"]), ("Bldg 2 91580", ["91580"]),
    ("Location 1 - 92478, Location 2 - 91580", ["92478", "91580"]), ("payroll of 39300", []),
    ("Sales $ 92478", []), ("12345 Main Street", []), ("92478 & 91580", ["92478", "91580"]),
    ("92478 91580", ["92478", "91580"]), ("Heating and air conditioning 92478", ["92478"]),
    ("91580 - Contractors - subcontracted work - in connection with construction", ["91580"]),
    ("Electrical work - within buildings - 92478 (contractors)", ["92478"]),
    ("12345 Main St: 92478", ["92478"]), ("Phone 3035551234", []), ("Zip 80221", []), ("92478-A", ["92478"]),
    ("No class codes", []), ("", []), (None, []),
])
def test_the_text_reader(text, want):
    assert gl_code_tokens_in_text(text) == want


@pytest.mark.parametrize("typed", [
    "Electrical contracting at 4800 Pecos St, Denver CO 80221", "Electrical contractor since 2015", "1731",
    "92478 electrical, payroll 39300", "Loc 1: 92478",
])
def test_the_score_still_counts_any_answer_as_present(typed):
    # Unchanged on purpose: the questionnaire asks this fact as "what type of
    # work at each location?", so a description is an answer. Only what PRINTS
    # moved; no score moves by this change.
    assert gl_class_codes_present({"gl_class_codes_by_location": _person(typed)})


def test_presence_reads_numbers_exactly_as_deployed():
    from services.sqs_service import _gl_code_tokens
    assert _gl_code_tokens(_person("Electrical at 4800 Pecos St, Denver CO 80221")) == (["4800", "80221"], True)
    assert _gl_code_tokens(_person("Electrical contracting")) == ([], False)
    assert _gl_code_tokens([{"location": "1", "codes": ["92478"]}]) == (["92478"], True)


# ── 3. the person's code beats one the documents were read for ───────────────

def test_a_persons_code_beats_an_ai_read_applicant_code():
    f = {"applicant_gl_class_code": {"value": "91340", "source": "ai"},
         "gl_class_codes_by_location": _person("92478")}
    assert _box("ACORD_125", GL, f) == "92478" == _box("ACORD_126", HZ + "A", f)


def test_an_ai_applicant_code_stands_when_no_person_gave_one():
    assert _box("ACORD_125", GL, {"applicant_gl_class_code": {"value": "91340", "source": "ai"}}) == "91340"
    f = {"applicant_gl_class_code": {"value": "91340", "source": "ai"},
         "gl_class_codes_by_location": [{"location": "1", "codes": ["92478"]}]}
    assert _box("ACORD_125", GL, f) == "91340"          # extraction shape, not a person's


def test_a_persons_own_applicant_code_stands():
    f = {"applicant_gl_class_code": _person("91340"), "gl_class_codes_by_location": _person("92478")}
    assert _box("ACORD_125", GL, f) == "91340"


def test_a_description_answer_leaves_the_ai_code_in_place():
    f = {"applicant_gl_class_code": {"value": "91340", "source": "ai"},
         "gl_class_codes_by_location": _person("Electrical contracting, commercial")}
    assert _box("ACORD_125", GL, f) == "91340"


# ── 4. another line's classes are never GL hazards ───────────────────────────

def _wc_rows_filed_under_gl():
    wc = [{"class_code": c, "classification": "State Act - " + n, "premium_basis": "Payroll",
           "exposure_amount": "$100,000"} for c, n in (("5190", "Electrical"), ("8742", "Sales"), ("8810", "Clerical"))]
    return {"gl_class_code_schedule": copy.deepcopy(wc), "wc_class_codes": copy.deepcopy(wc),
            "has_general_liability": True}


def test_wc_rows_in_the_gl_schedule_never_print_as_hazards():
    # The grid is then what it is on a package with no GL schedule at all.
    f = _wc_rows_filed_under_gl()
    bare = {"has_general_liability": True}
    assert [_box("ACORD_126", HZ + L, f) for L in "ABC"] == [_box("ACORD_126", HZ + L, bare) for L in "ABC"]
    assert not any(_printed(_box("ACORD_126", HZ + L, f)) for L in "ABC")
    assert not _printed(_box("ACORD_125", GL, f))


def test_the_persons_code_prints_when_the_schedule_is_another_lines():
    f = {**_wc_rows_filed_under_gl(), "gl_class_codes_by_location": _person("92478")}
    assert _box("ACORD_125", GL, f) == "92478"
    assert [_box("ACORD_126", HZ + L, f) for L in "AB"] == ["92478", None]


def test_a_real_gl_row_beside_a_wc_row_keeps_the_gl_row():
    f = _wc_rows_filed_under_gl()
    f["gl_class_code_schedule"].append({"class_code": "92478", "classification": "Electrical work",
                                        "premium_basis": "Payroll", "exposure_amount": "$500,000"})
    assert [_box("ACORD_126", HZ + L, f) for L in "AB"] == ["92478", None]
    assert _box("ACORD_125", GL, f) == "92478"


def test_a_gl_schedule_with_no_other_line_is_untouched():
    rows = [{"class_code": "91580", "classification": "Contractors - subcontracted work",
             "premium_basis": "Total Cost", "exposure_amount": "$350,000"},
            {"class_code": "91585", "classification": "Contractors - subcontracted work - other",
             "premium_basis": "Payroll", "exposure_amount": "$39,300"}]
    f = {"gl_class_code_schedule": rows, "has_general_liability": True}
    assert [_box("ACORD_126", HZ + L, f) for L in "ABC"] == ["91580", "91585", None]
    assert _box("ACORD_125", GL, f) == "91580, 91585"


# ── Guard 2e knows the person's code ──────────────────────────────────────────

@pytest.mark.parametrize("home", [
    {"gl_class_codes_by_location": _person("92478")},
    {"gl_class_code_schedule": [{"location": "1", "class_code": "92478", "classification": "Electrical",
                                 "premium_basis": "Payroll", "exposure_amount": "$500,000"}]},
])
def test_an_ai_copy_of_the_gl_code_into_a_127_rating_box_is_blanked(home):
    m = {"Vehicle_RateClassCode_A": "7398", "Vehicle_SpecialIndustryClassCode_A": "92478"}
    ps._enforce_post_fill_guards(m, _schema("ACORD_127"), {**home, "_form_id": "ACORD_127"},
                                 gpt_filled_set={"Vehicle_SpecialIndustryClassCode_A"})
    assert m["Vehicle_SpecialIndustryClassCode_A"] is None


def test_a_gl_row_copied_into_the_wc_table_stays_gl():
    # Three stored kits (26-27 Aug): extraction put the GL hazard row into
    # wc_class_codes as well. A five-digit ISO GL code another line's table
    # repeats is that misfile - the row prints, exactly as before.
    row = {"class_code": "91580", "classification": "Heating and Air Conditioning Systems",
           "premium_basis": "Payroll", "exposure_amount": "$1,240,000"}
    f = {"gl_class_code_schedule": [dict(row)], "has_general_liability": True,
         "wc_class_codes": [{"code": "91580", "description": "Heating and Air Conditioning Systems",
                             "state": "CO", "payroll": "$1,240,000"}]}
    assert _box("ACORD_126", HZ + "A", f) == "91580"
    assert _box("ACORD_125", GL, f) == "91580"


def test_a_by_location_row_with_no_iso_code_leaves_the_grid_an_owned_blank():
    # A NAICS code in the by-location home (stored 22 May, "Plot 45, Udyog
    # Vihar"): nothing to print, and no gap fill asked about classifications
    # the package does not have (the 11 Sep rule).
    f = {"gl_class_codes_by_location": [{"location": "Plot 45, Udyog Vihar", "codes": ["531120"]}],
         "has_general_liability": True}
    assert [_box("ACORD_126", HZ + L, f) for L in "AB"] == [None, None]
    f["gl_class_codes_by_location"] = [{"location": "1", "codes": ["92478"]}]
    assert [_box("ACORD_126", HZ + L, f) for L in "AB"] == ["92478", None]


def test_a_restamp_prints_only_what_generations_guards_allow():
    # The engine answers box by box; generation then runs the post-fill guards.
    # An employee count answered after forms used to land on ACORD 131's
    # named-insured rows B-F too, which the row de-dup guard blanks.
    facts = {"applicant_name": "Choice Electric LLC", "num_employees": {"value": "100", "source": "ai"}}
    gen = _generated(facts, ("ACORD_131",))
    rows = [f"BusinessInformation_EmployeeCount_{L}" for L in "ABCDEF"]
    assert [gen["ACORD_131"]["field_state"].get(b) for b in rows] == ["100", None, None, None, None, None]
    after = {**facts, "num_employees": _person("120")}
    moved = arq._restamp_changed_boxes(gen, facts, after, own_keys={"num_employees"}, own_value="120")
    assert moved == ["ACORD_131"]
    assert [gen["ACORD_131"]["field_state"].get(b) for b in rows] == ["120", None, None, None, None, None]
    assert gen["ACORD_131"]["confidence"]["BusinessInformation_EmployeeCount_A"] == "producer"


def test_a_by_location_gl_code_another_table_repeats_prints():
    # Stored May kits: the by-location GL code 91340 was copied into
    # wc_class_codes too. A five-digit GL code a WC table repeats is the Z14
    # misfile: the score counts it (Z32) and the 126 prints it (22 Oct 2026,
    # build 24 - this test pinned the old drop, which disagreed with the score).
    f = {"gl_class_codes_by_location": [{"location": "1245 Industrial Blvd, Aurora, CO 80011", "codes": ["91340"]}],
         "wc_class_codes": [{"code": "91340", "description": "Carpentry", "payroll": "$1,240,000"}],
         "has_general_liability": True}
    assert _box("ACORD_126", HZ + "A", f) == "91340"
