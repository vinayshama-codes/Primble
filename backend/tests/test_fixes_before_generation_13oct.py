"""The bugs on the owner's path to generating `18f6914f` (13 Oct 2026, "fix the remaining issues").

Each was found by replaying the owner's own answers through the real routes and stamping the forms:
  1. the driver table a PERSON typed lost DOB / licence / hire date / years on ACORD 127 (40 boxes);
  2. a remarks paragraph saying "no reported losses" was stored EMPTY (and emptied the remarks on file);
  3. `operations_description` = "LOCAL SERVICE" (a vehicle schedule's use column) stood as the business
     description, with no way to replace it before generation;
  4. two buildings on one street lost building 2's ACORD 125 premises row; seventeen vehicles' own
     $1,000 deductibles were blanked on rows B-D as "repeats" of row A;
  5. a box window whose rule needs every box (Minimum Viable COPE) said "Apply" on a partial fix.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import services.pdf_service as ps
from services.answer_semantics import interpret_answer
from services.extraction_service import drop_vehicle_use_descriptions
from services.issue_registry import resolution_for
from services.normalization import (description_restates_vehicle_use, is_vehicle_use_label,
                                    vehicle_use_as_operations)
from services.schedule_capture import mark_human_rows
from services.sqs_service import key_details

_FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"

_DRIVERS = [
    {"name": "Marcus Delgado", "dob": "03/14/1979", "license_number": "08-417-2291",
     "license_state": "CO", "hire_date": "06/02/2008", "experience_years": "29"},
    {"name": "Tyler Brennan", "dob": "11/02/1986", "license_number": "11-208-5573",
     "license_state": "CO", "hire_date": "03/15/2012", "experience_years": "21"},
]


def _stamp(facts, form_id):
    from services.form_dry_run import stamp_forms
    gen, problems = stamp_forms({"docs": []}, [form_id], facts, {})
    assert not problems, problems
    return gen[form_id]["mapped"], gen[form_id]["guard_blanks"]


# ── 1. A person's driver table prints ──────────────────────────────────────────
def test_a_person_typed_driver_table_prints_every_column():
    facts = {"auto_drivers": [dict(d) for d in _DRIVERS]}
    mark_human_rows(facts, "auto_drivers", "producer")
    mapped, blanks = _stamp(facts, "ACORD_127")
    assert mapped.get("Driver_BirthDate_A") == "03/14/1979"
    assert mapped.get("Driver_LicenseNumberIdentifier_A") == "08-417-2291"
    assert mapped.get("Driver_LicensedStateOrProvinceCode_B") == "CO"
    assert mapped.get("Driver_HiredDate_B") == "03/15/2012"
    assert mapped.get("Driver_ExperienceYearCount_B") == "21"
    assert not [b for b in blanks if str(b.get("field", "")).startswith("Driver_")]


def test_an_unmarked_driver_record_is_still_cleared():
    """The guard's own case stands: personal columns from a record no person saved."""
    facts = {"auto_drivers": [dict(d) for d in _DRIVERS]}
    mapped, _ = _stamp(facts, "ACORD_127")
    assert not mapped.get("Driver_BirthDate_A")
    assert not mapped.get("Driver_LicenseNumberIdentifier_A")


def test_a_table_changed_after_the_person_saved_it_is_not_theirs():
    facts = {"auto_drivers": [dict(d) for d in _DRIVERS]}
    mark_human_rows(facts, "auto_drivers", "producer")
    facts["auto_drivers"][0]["dob"] = "01/01/1970"       # a later writer, not the person
    mapped, _ = _stamp(facts, "ACORD_127")
    assert not mapped.get("Driver_BirthDate_A")


# ── 2. The ACORD 101 remarks keep prose; every other fact reads as before ────
@pytest.mark.parametrize("text", [
    "Loss history: no reported losses and no claims in the past five years; the insured has never had a gap.",
    "Coverage discussion: EPL is not applicable to the umbrella; loss runs will follow later from the incumbent.",
    "Roof replaced 2019\nNo losses",          # the reviewer's composed remarks (a)
    "New venture.\nNo prior coverage",         # (b)
    "No losses in five years",                  # (c) - no remarks on file
    "No known losses",
])
def test_remarks_prose_is_kept_at_any_length(text):
    out = interpret_answer("additional_remarks_text", text)
    assert out.intent == "value" and out.value == text, out


@pytest.mark.parametrize("text,intent", [
    ("None", "absence"), ("no remarks", "absence"), ("Nothing to add", "absence"),
    ("N/A", "not_applicable"), ("TBD", "unknown"), ("TBD - will confirm later", "unknown"),
])
def test_a_short_whole_answer_in_the_remarks_reads_as_before(text, intent):
    assert interpret_answer("additional_remarks_text", text).intent == intent


@pytest.mark.parametrize("fact,text,intent", [
    # the reviewer's HIGH findings: a non-answer stays refused, a denial stays held (F7)
    ("operations_description", "I'm not sure, will ask my accountant", "unknown"),
    ("operations_description", "Will send this information to you later", "unknown"),
    ("operations_description", "TBD - will confirm with insured later", "unknown"),
    ("operations_description", "We do not have any operations at all", "absence"),
    ("operations_description", "N/A - we are a holding company only", "not_applicable"),
    ("wc_description_of_operations", "Not applicable to our business at all", "not_applicable"),
    ("prior_carrier_name", "We have never had insurance before this year", "absence"),
    ("operations_description", "Commercial electrical contractor - new construction and service work.", "value"),
])
def test_every_other_fact_reads_exactly_as_before(fact, text, intent):
    assert interpret_answer(fact, text).intent == intent


def test_the_narrative_door_judges_the_new_words_and_never_wipes_the_remarks():
    import asyncio
    from unittest.mock import patch
    import services.arq_service as arq
    stored = {}

    async def _get(_sid):
        return {"facts": {"additional_remarks_text": {"value": "Roof replaced 2019", "source": "producer"}}}

    async def _apply(_sid, field, value, **_k):
        stored[field] = value
        return True, []

    with patch("repositories.session_repository.get_processing_session", _get), \
         patch.object(arq, "apply_producer_answer_to_session", _apply):
        assert asyncio.run(arq.append_producer_narrative("s", "None"))[0] is False
        assert asyncio.run(arq.append_producer_narrative("s", "TBD"))[0] is False
        ok, _ = asyncio.run(arq.append_producer_narrative("s", "No losses"))
    assert ok is True
    assert stored["additional_remarks_text"] == "Roof replaced 2019\nNo losses"
    assert interpret_answer("additional_remarks_text", stored["additional_remarks_text"]).intent == "value"


# ── 3. A vehicle's use class is not the business description ──────────────────
@pytest.mark.parametrize("value,expected", [
    ("LOCAL SERVICE", True), ("Intermediate", True), ("Long distance commercial", True),
    ("local", True), ("Retail", False), ("Commercial", False), ("Service", False),
    ("Electrical contractor - local service work", False), ("", False), (None, False),
    ("Local delivery of electrical supplies to job sites in the metro area", False),
    ("LONG DISTANCE HAULING", False), ("Local hauling", False), ("LONG HAUL", False),
])
def test_vehicle_use_labels(value, expected):
    assert is_vehicle_use_label(value) is expected


@pytest.mark.parametrize("description,use,expected", [
    ("LOCAL SERVICE", "service", True),            # 18f6914f
    ("LOCAL SERVICE", None, False),                # no vehicle use stated: vocabulary alone never decides
    ("Local retail business", "service", False),   # the reviewer's real descriptions
    ("Local farm", "service", False),
    ("Long distance commercial", "commercial", True),
    ("LONG DISTANCE HAULING", "commercial", False),
])
def test_only_a_restated_vehicle_use_is_ruled_out(description, use, expected):
    assert description_restates_vehicle_use(description, use) is expected


def test_the_merge_drops_a_vehicle_use_description_per_document():
    dfacts = {"operations_description": {"value": "LOCAL SERVICE", "source": "ai"},
              "auto_vehicle_use": {"value": "service", "source": "ai"},
              "account_description": "Electrical contractor", "applicant_name": "X LLC"}
    assert drop_vehicle_use_descriptions(dfacts) == ["operations_description"]
    assert "account_description" in dfacts and "operations_description" not in dfacts
    # a trucker's real description on a document with a vehicle schedule stays
    hauler = {"operations_description": "LONG DISTANCE HAULING", "auto_vehicle_use": "commercial"}
    assert drop_vehicle_use_descriptions(hauler) == [] and "operations_description" in hauler


def test_the_review_asks_for_it_with_a_fix():
    ai = {"operations_description": {"value": "LOCAL SERVICE", "source": "ai"}, "fein": "84-1234567",
          "auto_vehicle_use": {"value": "service", "source": "ai"}}
    kd = key_details(ai, {})
    assert "Operations description" in kd["missing"]
    item = next(i for i in kd["missing_items"] if i["label"] == "Operations description")
    assert item["resolution"] == {"mode": "field", "facts": ["operations_description"]}
    # a person's own words always count
    mine = {"operations_description": {"value": "Local service", "source": "producer"},
            "auto_vehicle_use": "service"}
    assert "Operations description" not in key_details(mine, {})["missing"]
    confirmed = {"operations_description": {"value": "LOCAL SERVICE", "source": "ai",
                                            "evidence_state": "user_confirmed"}, "auto_vehicle_use": "service"}
    assert "Operations description" not in key_details(confirmed, {})["missing"]


def test_one_ruling_for_the_stamper_the_prefill_and_the_questionnaire():
    from services.arq_service import _present_fact_keys
    facts = {"operations_description": {"value": "LOCAL SERVICE", "source": "ai"},
             "auto_vehicle_use": {"value": "service", "source": "ai"}}
    assert vehicle_use_as_operations(facts) is True
    assert "operations_description" not in _present_fact_keys(facts)       # the client is asked
    mapped, _ = _stamp(facts, "ACORD_125")
    assert not [k for k, v in mapped.items() if "OperationsDescription" in k and v == "LOCAL SERVICE"]
    src = (Path(__file__).resolve().parents[1] / "routes" / "audit_routes.py").read_text(encoding="utf-8")
    assert '_not_an_answer = {"operations_description"} if vehicle_use_as_operations(sess_facts) else set()' in src


def test_the_remarks_keep_their_own_card():
    """Only a prose fact of its own gets the typed window; ACORD 101 remarks stay the Narrative card's."""
    from services.sqs_service import _key_detail_actions
    for it in _key_detail_actions({}, {}):
        assert "additional_remarks_text" not in ((it.get("resolution") or {}).get("facts") or [])


# ── 4. Rows a record states are not repeats ───────────────────────────────────
def test_two_buildings_on_one_street_keep_both_premises_rows():
    mapped = {
        "CommercialStructure_PhysicalAddress_LineOne_A": "4800 Washington St",
        "CommercialStructure_PhysicalAddress_CityName_A": "Denver",
        "CommercialStructure_PhysicalAddress_PostalCode_A": "80216",
        "CommercialStructure_Building_ProducerIdentifier_A": "001",
        "CommercialStructure_PhysicalAddress_LineOne_B": "4800 Washington St",
        "CommercialStructure_PhysicalAddress_CityName_B": "Denver",
        "CommercialStructure_PhysicalAddress_PostalCode_B": "80216",
        "CommercialStructure_Building_ProducerIdentifier_B": "002",
    }
    assert ps._dedupe_stamped_premises_rows(mapped, set()) == []
    assert mapped["CommercialStructure_PhysicalAddress_LineOne_B"] == "4800 Washington St"


def test_one_premises_printed_twice_still_folds():
    """The guard's own case (2026-08-14): the same address re-read with no building of its own."""
    mapped = {
        "CommercialStructure_PhysicalAddress_LineOne_A": "4800 Dahlia St # D13",
        "CommercialStructure_PhysicalAddress_PostalCode_A": "80216",
        "CommercialStructure_PhysicalAddress_LineOne_B": "4800 Dahlia St D13 Denver",
        "CommercialStructure_PhysicalAddress_PostalCode_B": "80216",
    }
    assert "CommercialStructure_PhysicalAddress_LineOne_B" in ps._dedupe_stamped_premises_rows(mapped, set())


def test_the_location_table_rows_print_on_the_125():
    facts = {"property_locations": [
        {"location_id": "L1", "location_number": "1", "building_number": "001",
         "address_line1": "4800 Washington St", "address_city": "Denver", "address_state": "CO",
         "address_zip": "80216", "construction_type": "FRAME"},
        {"location_id": "L2", "location_number": "1", "building_number": "002",
         "address_line1": "4800 Washington St", "address_city": "Denver", "address_state": "CO",
         "address_zip": "80216", "construction_type": "NON-COMBUSTIBLE"},
    ]}
    mapped, _ = _stamp(facts, "ACORD_125")
    assert mapped.get("CommercialStructure_PhysicalAddress_LineOne_B") == "4800 Washington St"
    assert mapped.get("CommercialStructure_Building_ProducerIdentifier_B") == "002"


def test_every_vehicle_keeps_the_schedules_deductible():
    facts = {"auto_vin_schedule": [{"year": "2017", "make": "CHEVROLET", "model": "EXPRESS"}] * 4,
             "auto_deductible_comp": "$1,000", "auto_deductible_collision": "$1,000"}
    facts["auto_vin_schedule"] = [dict(v, vin=f"1GCWGAFP{n}H1234567"[:17]) for n, v in
                                  enumerate(facts["auto_vin_schedule"])]
    mapped, blanks = _stamp(facts, "ACORD_127")
    for r in "ABCD":
        assert mapped.get(f"Vehicle_Collision_DeductibleAmount_{r}") == "1,000", r
    assert not [b for b in blanks if "DeductibleAmount" in str(b.get("field"))]


# ── 5. "Save progress" on a box window whose rule needs every box ─────────────
def test_cope_cards_declare_what_they_need_and_copies_are_independent():
    for code in ("minimum_viable_cope_missing", "legacy_minimum_viable_cope"):
        res = resolution_for(code)
        assert res["needs"] == [["occupancy_type"], ["construction_type"],
                                ["property_building_value", "property_bpp_value"]], code
        res["needs"][2].append("x")
        assert "x" not in resolution_for(code)["needs"][2]
    # "whichever applies" windows declare nothing
    assert "needs" not in (resolution_for("tier1_missing_Contact information") or {})


def _node(tmp_path, body):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / "check.mjs"
    script.write_text(f"import * as P from {json.dumps((_FRONT / 'utils' / 'fixProgress.js').as_uri())};\n"
                      + body + "\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_the_window_names_the_unmet_groups(tmp_path):
    needs = [["occupancy_type"], ["construction_type"], ["property_building_value", "property_bpp_value"]]
    out = _node(tmp_path, f"""
const needs = {json.dumps(needs)};
const L = (f) => f.toUpperCase();
console.log(JSON.stringify([
  P.unmetNeeds(needs, {{}}, L),
  P.unmetNeeds(needs, {{occupancy_type: 'Office', construction_type: 'FRAME'}}, L),
  P.unmetNeeds(needs, {{occupancy_type: 'Office', construction_type: 'FRAME', property_bpp_value: '73008'}}, L),
  P.unmetNeeds(null, {{}}, L),
]));
""")
    assert out == [
        "OCCUPANCY_TYPE; CONSTRUCTION_TYPE; PROPERTY_BUILDING_VALUE or PROPERTY_BPP_VALUE",
        "PROPERTY_BUILDING_VALUE or PROPERTY_BPP_VALUE",
        "",
        "",
    ]


def test_the_window_uses_the_declaration():
    src = (_FRONT / "components" / "form" / "ResolutionModal.jsx").read_text(encoding="utf-8")
    assert "unmetNeeds(resolution.needs, values, humanizeFact)" in src
    assert "progressGap\n                      ? 'Save progress'" in src
    assert "{ allowConfirm: !note && !progressGap }" in src
    assert "fieldFacts.length > 1 && !Array.isArray(resolution.needs) && (" in src


# ── 6. The review's findings on fixes 4 and 5 (13 Oct night) ──────────────────
def test_a_client_typed_table_without_building_numbers_keeps_building_two():
    """Review finding: a client's table has no BLDG # (producer-only); the fold deleted building 2's
    row on the 140 - its year built included - and raised a download hard stop."""
    facts = {"property_locations": [
        {"location_id": "L1", "location_number": "1", "address_line1": "4800 Washington St",
         "address_city": "Denver", "address_state": "CO", "address_zip": "80216",
         "construction_type": "FRAME", "year_built": "1998"},
        {"location_id": "L2", "location_number": "2", "address_line1": "4800 Washington St",
         "address_city": "Denver", "address_state": "CO", "address_zip": "80216",
         "construction_type": "NON-COMBUSTIBLE", "year_built": "2006"},
    ]}
    mark_human_rows(facts, "property_locations", "client_arq")
    mapped, _ = _stamp(facts, "ACORD_140")
    assert mapped.get("CommercialStructure_BuiltYear_B") == "2006"
    mapped125, _ = _stamp(facts, "ACORD_125")
    assert mapped125.get("CommercialStructure_PhysicalAddress_LineOne_B") == "4800 Washington St"


def test_gap_fill_numbering_its_own_duplicate_rows_still_folds():
    """Review finding: a BLDG # gap fill authored (or '001' vs '1') is no evidence of a second building."""
    mapped = {
        "CommercialStructure_PhysicalAddress_LineOne_A": "4800 Dahlia St # D13",
        "CommercialStructure_PhysicalAddress_PostalCode_A": "80216",
        "CommercialStructure_Building_ProducerIdentifier_A": "001",
        "CommercialStructure_PhysicalAddress_LineOne_B": "4800 Dahlia St D13 Denver",
        "CommercialStructure_PhysicalAddress_PostalCode_B": "80216",
        "CommercialStructure_Building_ProducerIdentifier_B": "2",
        "CommercialStructure_PhysicalAddress_LineOne_C": "4800 Dahlia St D13",
        "CommercialStructure_PhysicalAddress_PostalCode_C": "80216",
        "CommercialStructure_Building_ProducerIdentifier_C": "1",
    }
    gap = {"CommercialStructure_Building_ProducerIdentifier_B",
           "CommercialStructure_PhysicalAddress_LineOne_B"}
    dropped = ps._dedupe_stamped_premises_rows(mapped, gap)
    assert "CommercialStructure_PhysicalAddress_LineOne_B" in dropped    # gap fill's own "2"
    assert "CommercialStructure_PhysicalAddress_LineOne_C" in dropped    # "1" == "001"


def test_a_137_section_never_takes_a_vehicles_deductible():
    facts = {"_form_id": "ACORD_137_CA", "auto_vin_schedule": [{"year": "2017"}] * 4,
             "auto_deductible_collision": "$1,000"}
    assert ps._resolve_vehicle_deductible_cell("Vehicle_Collision_DeductibleAmount_B", facts) is ps._SCHED_SKIP


def test_one_location_prints_once_on_the_130():
    mapped = {
        "Location_ProducerIdentifier_A": "1", "Location_PhysicalAddress_LineOne_A": "4800 Washington St",
        "Location_PhysicalAddress_PostalCode_A": "80216", "Location_HighestFloorCount_A": "2",
        "Location_ProducerIdentifier_B": "1", "Location_PhysicalAddress_LineOne_B": "4800 Washington St",
        "Location_PhysicalAddress_PostalCode_B": "80216", "Location_HighestFloorCount_B": "1",
        "Location_ProducerIdentifier_C": "2", "Location_PhysicalAddress_LineOne_C": "4800 Washington St",
    }
    dropped = ps._dedupe_repeated_location_rows(mapped)
    assert mapped["Location_PhysicalAddress_LineOne_B"] is None and "Location_HighestFloorCount_B" in dropped
    assert mapped["Location_PhysicalAddress_LineOne_C"] == "4800 Washington St"   # another LOC #
    assert mapped["Location_PhysicalAddress_LineOne_A"] == "4800 Washington St"


def test_the_building_table_declares_its_row_needs_and_stored_cards_get_needs():
    from services.premises_cope import route_cope_resolution
    from services.issue_registry import _with_current_needs
    facts = {"property_locations": [{"location_id": "L1", "address_line1": "1 A St"},
                                    {"location_id": "L2", "address_line1": "1 A St"}]}
    res = route_cope_resolution("legacy_minimum_viable_cope", resolution_for("legacy_minimum_viable_cope"), facts)
    assert res["mode"] == "schedule"
    assert res["row_needs"] == [["construction_type"], ["building_value", "bpp_value"]]
    stored = {"mode": "field", "facts": ["occupancy_type", "construction_type"]}
    assert _with_current_needs(stored, "minimum_viable_cope_missing")["needs"][0] == ["occupancy_type"]
    assert "needs" not in _with_current_needs({"mode": "field", "facts": ["x"]}, "tier1_missing_Contact information")


def test_the_twin_taking_over_and_a_buildings_missing_column(tmp_path):
    coded = {"issue_id": "iss_c", "code": "carrier_grade_cope_incomplete", "cluster": "Property COPE quality",
             "message": "Carrier-Grade COPE quality fields missing: roof year, protection class"}
    legacy = {"issue_id": "iss_l", "code": "legacy_carrier_grade_cope", "cluster": "Property COPE quality",
              "message": "Carrier-Grade COPE incomplete - SQS capped at 85. Missing: roof year"}
    other = {"issue_id": "iss_o", "code": "x", "cluster": "Auto completeness", "message": "Something else"}
    cols = [{"key": "address_line1", "label": "Street address", "required": True},
            {"key": "construction_type", "label": "Construction"},
            {"key": "building_value", "label": "Building value"}, {"key": "bpp_value", "label": "BPP value"}]
    rows = [{"address_line1": "1 A St", "construction_type": "FRAME", "bpp_value": "73008"},
            {"address_line1": "1 A St", "building_value": "421714"}, {}]
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / "t.mjs"
    script.write_text(f"""import * as P from {json.dumps((_FRONT / 'utils' / 'fixProgress.js').as_uri())};
const idOf = (i) => i.issue_id;
const grouped = (items) => ({{ warnings: {{ recommended: [{{ cluster: items[0].cluster, items }}] }} }});
console.log(JSON.stringify([
  P.fixLeftOpen({json.dumps(coded)}, P.listedIssues({{ grouped: grouped([{json.dumps(coded)}]) }}),
                P.listedIssues({{ grouped: grouped([{json.dumps(legacy)}]) }}), idOf),
  P.fixLeftOpen({json.dumps(coded)}, P.listedIssues({{ grouped: grouped([{json.dumps(coded)}]) }}),
                P.listedIssues({{ grouped: grouped([{json.dumps(other)}]) }}), idOf),
  P.rowNeedsSummary({json.dumps(rows)}, [["construction_type"], ["building_value", "bpp_value"]], {json.dumps(cols)}),
]));
""", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    twin, unrelated, gap = json.loads(run.stdout)
    assert twin is True and unrelated is False
    assert gap == "Construction on row 2"
    src = (_FRONT / "components" / "form" / "ResolutionModal.jsx").read_text(encoding="utf-8")
    # + the server's building rule (21 Oct 2026, review M1 - the pin named the old call)
    assert "rowNeedsSummary(rows, resolution.row_needs, schedule.columns || [], resolution.building_columns)" in src


def test_the_narrative_card_names_the_missing_depth():
    """Owner, 13 Oct 2026: every topic covered, yet the card said only "Improve narrative quality"."""
    from services.sqs_service import narrative_substance_gaps
    text = ("Account overview: family-owned contractor in business since 2008. Loss history: loss free. "
            "Risk controls: written safety program. Renewal of the program. Umbrella limits. "
            "Annual revenue $4.5M. Owners are licensed master electricians.")
    assert narrative_substance_gaps(text) == ["the scope of work (what the work primarily consists of)"]
    assert narrative_substance_gaps(text + " Work consists of wiring and panel upgrades.") == []
    src = (Path(__file__).resolve().parents[1] / "services" / "sqs_service.py").read_text(encoding="utf-8")
    assert '"Narrative covers every topic - add " + _words_list(_thin)' in src


def test_the_narrative_window_offers_every_missing_item_as_a_starter():
    """Owner, 13 Oct 2026: "user wont know what is happening ... use multiselect options"."""
    from services.sqs_service import (narrative_gap_options, _score_narrative_substance,
                                      NARRATIVE_SUBSTANCE_STARTERS, _NARRATIVE_SUBSTANCE_SIGNALS)
    opts = narrative_gap_options({"account_overview": False, "operations": True}, "Operations: wiring.")
    keys = [o["key"] for o in opts]
    assert "topic:account_overview" in keys and "topic:operations" not in keys
    assert "depth:specific_operations_detail" in keys
    # every starter carries the phrase its own check reads, so finishing it clears the item
    for k, starter in NARRATIVE_SUBSTANCE_STARTERS.items():
        assert any(p in starter.lower() for p in _NARRATIVE_SUBSTANCE_SIGNALS[k]), k
    assert narrative_gap_options({"operations": True}, " ".join(NARRATIVE_SUBSTANCE_STARTERS.values())) == []
    src = (Path(__file__).resolve().parents[1] / "services" / "sqs_service.py").read_text(encoding="utf-8")
    assert '"narrative_gaps": narrative_gap_options(' in src
    rec = (_FRONT / "utils" / "recommendations.js").read_text(encoding="utf-8")
    assert "resolution = { ...resolution, gaps: row.narrative_gaps };" in rec
    modal = (_FRONT / "components" / "form" / "ResolutionModal.jsx").read_text(encoding="utf-8")
    assert "Still missing - tick to add a starter" in modal and "resolution.gaps.map((g) =>" in modal
