"""Brent's 17 Oct item 6 (21 Oct 2026): ONE "General Liability Classification &
Exposure Details" window.

Before: two GL cards with two pop-ups - "GL coverage detected but no class codes
found" (one free-text box on `gl_class_codes_by_location`) and "GL coverage
detected but no revenue or payroll found" (revenue + payroll boxes) - while the
extracted `gl_class_code_schedule` fed the ACORD 126 hazard grid with no window
of its own.

Now:
  * a capture table on the EXISTING `gl_class_code_schedule` fact
    (`schedule_capture.SCHEDULE_DEFS`), every column a real 126 hazard box,
    producer-only, with a per-row "Unknown - follow up" mark;
  * both GL warnings open it, and the review shows them as ONE item
    (`issue_registry._fold_one_item_tables`);
  * the score's two GL readers read its rows; the 126 stamps them through the
    grid's own door; the 125 GL CODE takes a person's codes.

The adversarial cases are written first in each section: what a binding, a fold
or a reader could over-reach into.
"""
from __future__ import annotations

import copy
import glob
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from services import answer_routing as AR
from services import issue_registry as IR
from services import pdf_service as ps
from services import schedule_capture as sc
from services import sqs_service as sq

BACKEND = Path(__file__).resolve().parents[1]
FRONT = BACKEND.parent / "frontend" / "src"
SCHEMAS = BACKEND / "forms_schemas"
GL = "gl_class_code_schedule"
GL_CODES = "GL coverage detected but no class codes found"
GL_EXPOSURE = "GL coverage detected but no revenue or payroll found"
HAZARD_COLUMNS = ("LocationProducerIdentifier", "HazardProducerIdentifier", "ClassCode",
                  "Classification", "PremiumBasisCode", "Exposure", "TerritoryCode")
GLF = {"has_general_liability": True}


def _schema(form_id: str) -> dict:
    return json.loads((SCHEMAS / f"{form_id}_schema.json").read_text(encoding="utf-8"))


def _row(**kw) -> dict:
    return dict(kw)


def _premises(*nums_addr):
    out = []
    for n, (num, line1) in enumerate(nums_addr):
        out.append({"location_number": num, "building_number": "1", "address_line1": line1,
                    "address_city": "Denver", "address_state": "CO", "address_zip": "80216",
                    "location_id": f"L{n + 1}"})
    return out


def _wc_misfiled() -> dict:
    """A combined package whose GL schedule also holds a WC class (live shape,
    Choice Electric ca93ed8f: 5190 / 8742 / 8810 filed under GL)."""
    return {
        "wc_class_codes": [{"code": "5190", "description": "Electrical wiring", "payroll": "$1,200,000",
                            "state": "CO"}],
        GL: [{"class_code": "5190", "classification": "Electrical Wiring Within Buildings",
              "premium_basis": "Payroll", "exposure_amount": "$1,200,000"}],
    }


def _soft(facts):
    return [s for s in sq.evaluate_stops(facts, GLF)[1] if s.startswith("GL coverage detected")]


# ═════════════════════════════════════════════════════════════════════════════
# 1. The binding names the column - it never takes over stamping or gap fill
# ═════════════════════════════════════════════════════════════════════════════

def test_every_gl_table_column_binds_a_live_acord_126_box():
    """The guard `test_schedule_capture::test_every_schedule_column_binds_to_a_
    live_acord_field`, replayed for the GL table: each column is a real box."""
    live = set()
    for path in glob.glob(str(SCHEMAS / "*.json")):
        for field in json.loads(Path(path).read_text(encoding="utf-8")):
            m = ps._SCHED_ROW_RE.match(field)
            d = ps._schedule_def_for_base(m.group(1)) if m else None
            if d is not None and d.list_key == GL:
                live.add((Path(path).name, d.sub_key))
    keys = {c["key"] for c in sc.SCHEDULE_DEFS[GL]["columns"]}
    assert {k for _f, k in live} == keys
    assert {f for f, _k in live} == {"ACORD_126_schema.json"}


def test_the_binding_keys_are_rooted_nowhere_on_any_form():
    """ADVERSARIAL. Every root-based sweep derives roots from the registry KEYS;
    "GeneralLiability" is also the root of ACORD 160's and ACORD 25's other
    coverage rows. The GL keys' root must be no real field's root."""
    roots = {f.split("_", 1)[0] for p in glob.glob(str(SCHEMAS / "*.json"))
             for f in json.loads(Path(p).read_text(encoding="utf-8"))}
    gl_keys = [k for k, d in ps._SCHEDULE_REGISTRY.items() if d.list_key == GL]
    assert len(gl_keys) == 5
    assert not ({k.split("_", 1)[0] for k in gl_keys} & roots)
    assert "GeneralLiability" not in ps._schedule_family_list_keys()
    assert "GeneralLiability" not in ps._schedule_root_bindings()
    assert sc.row_family_roots(GL) and not (sc.row_family_roots(GL) & roots)


@pytest.mark.parametrize("field", [
    "GeneralLiability_OtherCoverageCode_B",          # ACORD 160
    "GeneralLiability_OtherCoverageDescription_B",   # ACORD 25
    "GeneralLiability_OtherCoverageLimitAmount_K",   # ACORD 160
])
def test_other_forms_general_liability_rows_are_not_this_tables_family(field):
    """ADVERSARIAL. With ONE GL row, a family / phantom sweep keyed on the
    "GeneralLiability" root would blank every other-coverage row past row A."""
    facts = {GL: [_row(location="Location 1", class_code="91580")]}
    assert ps._resolve_schedule_family_row(field, facts) is ps._SCHED_SKIP
    assert ps._resolve_phantom_schedule_row(field, facts) is ps._SCHED_SKIP


@pytest.mark.parametrize("col", HAZARD_COLUMNS)
@pytest.mark.parametrize("letter", "ABC")
def test_the_generic_schedule_resolver_steps_aside_for_every_hazard_cell(col, letter):
    """The grid keeps its one door: the generic resolver never answers a hazard
    box (it would print "Payroll" in a code box and the raw location string in
    LOC #), and gap fill keeps its view of the grid (`_is_schedule_field`)."""
    field = f"GeneralLiability_Hazard_{col}_{letter}"
    facts = {GL: [_row(location="Location 1", class_code="91580", premium_basis="Payroll",
                       exposure_amount="100")]}
    assert ps._resolve_schedule_row(field, facts) is ps._SCHED_SKIP
    assert ps._is_schedule_field(field) is False
    assert ps.schedule_box_value(field, facts) == ps._resolve_gl_hazard_row(field, facts)


def test_the_real_126_stamper_prints_the_window_rows_through_the_grid_door():
    schema = _schema("ACORD_126")
    facts = {
        GL: [_row(location="Location 001", class_code="92478", classification="Electrical work",
                  premium_basis="Payroll", exposure_amount="1,400,000", territory="104"),
             _row(location="Location 1 - 4800 Dahlia St, Denver, CO 80216", class_code="91580",
                  classification="Contractors", premium_basis="Total Cost", exposure_amount="350000"),
             _row(location="Location 1 - 4800 Dahlia St, Denver, CO 80216",
                  classification="Something not known yet", follow_up=True)],
        "property_locations": _premises(("1", "4800 Dahlia St")),
    }
    mapped, _conf = ps.map_facts_to_form(facts, schema, "ACORD_126", raw_text="", allow_llm=False)
    got = {c: [mapped.get(f"GeneralLiability_Hazard_{c}_{r}") for r in "ABC"] for c in HAZARD_COLUMNS}
    assert got["LocationProducerIdentifier"] == ["1", "1", "1"]          # one premises, two spellings
    assert got["HazardProducerIdentifier"] == ["1", "2", "3"]            # unique WITHIN the location
    assert got["ClassCode"] == ["92478", "91580", None]
    assert got["PremiumBasisCode"] == ["P", "C", None]                   # ACORD's letter, never the word
    assert got["Exposure"] == ["1,400,000", "350000", None]
    assert got["TerritoryCode"][0] == "104" and not got["TerritoryCode"][1]
    assert got["Classification"][2] == "Something not known yet"
    # a follow-up row's blanks are OWNED: gap fill is never asked to guess them
    _m, unmatched, _f = ps.compute_form_gaps("ACORD_126", schema, facts)
    assert not [k for k in unmatched if k.startswith("GeneralLiability_Hazard")]


def test_an_extracted_row_with_an_empty_cell_still_reaches_gap_fill():
    """Unchanged behaviour: only a row a PERSON marked prints nothing it does
    not have - a document's row with no basis still lets gap fill read it."""
    facts = {GL: [_row(location="Location 1", class_code="91580")]}
    assert ps._resolve_gl_hazard_row("GeneralLiability_Hazard_PremiumBasisCode_A", facts) == "UNMATCHED"
    assert ps._resolve_phantom_gl_hazard_row("GeneralLiability_Hazard_PremiumBasisCode_A", facts) \
        is ps._SCHED_SKIP
    marked = {GL: [_row(location="Location 1", class_code="91580", follow_up=True)]}
    assert ps._resolve_gl_hazard_row("GeneralLiability_Hazard_PremiumBasisCode_A", marked) is None
    assert ps._resolve_phantom_gl_hazard_row("GeneralLiability_Hazard_PremiumBasisCode_A", marked) is None
    assert ps._resolve_gl_hazard_row("GeneralLiability_Hazard_ClassCode_A", marked) == "91580"


def test_the_hazard_number_groups_rows_by_the_location_number_they_print():
    rows = [_row(location="001"), _row(location="001"), _row(location="002")]
    assert [ps._hazard_ordinal_within_location(rows, i) for i in range(3)] == ["001", "002", "001"]
    facts = {"property_locations": _premises(("1", "4800 Dahlia St"))}
    mixed = [_row(location="Location 001"), _row(location="Location 1 - 4800 Dahlia St")]
    assert [ps._hazard_ordinal_within_location(mixed, i, facts) for i in range(2)] == ["1", "2"]
    assert ps._hazard_ordinal_within_location([_row(class_code="91340")], 0, facts) == "UNMATCHED"


def test_the_questionnaire_still_asks_hazard_boxes_as_it_did():
    """The GL table is the producer's window, not a questionnaire table: the
    exact-binding test (`binds_a_capturable_column`) and the form's tables
    (`schedules_on_form`) do not change, so hazard boxes stay ordinary items."""
    from services.arq_service import _partition_schedule_fields
    assert GL not in sc.schedules_on_form("ACORD_126")
    assert not sc.binds_a_capturable_column("GeneralLiability_Hazard_ClassCode_A")
    missing = {"GeneralLiability_Hazard_ClassCode_A": ["ACORD_126"],
               "GeneralLiability_Hazard_Exposure_B": ["ACORD_126"]}
    out = _partition_schedule_fields(missing, {}, {"ACORD_126": _schema("ACORD_126")}, {})
    assert GL not in out and set(missing) == {"GeneralLiability_Hazard_ClassCode_A",
                                              "GeneralLiability_Hazard_Exposure_B"}


# ═════════════════════════════════════════════════════════════════════════════
# 2. The table
# ═════════════════════════════════════════════════════════════════════════════

def test_the_table_is_declared_on_the_existing_fact():
    d = sc.SCHEDULE_DEFS[GL]
    assert [c["key"] for c in d["columns"]] == ["location", "classification", "class_code",
                                                 "premium_basis", "exposure_amount"]
    assert d["producer_only"] is True and sc.is_producer_only(GL)
    assert sc.capacity_for(GL) == 3                     # the 126 prints rows A-C
    assert d["follow_up"] is True and d["answers"] == ["gl_class_codes_by_location"]
    assert d["title"] == "General Liability Classification & Exposure Details"
    assert GL in sc.MERGE_ON_SAVE
    assert "—" not in json.dumps(d, ensure_ascii=False)   # no em-dash in UI text
    assert "—" not in json.dumps(sc.columns_for(GL, {"operations_description": "x"}),
                                      ensure_ascii=False)
    # the code is never suggested: no example, no choices
    code = next(c for c in d["columns"] if c["key"] == "class_code")
    assert not code.get("placeholder") and not code.get("options")


def test_the_other_tables_are_byte_identical():
    for key, d in sc.SCHEDULE_DEFS.items():
        if key == GL:
            continue
        for extra in ("follow_up", "answers", "review_item", "title", "intro", "restamp_derived"):
            assert extra not in d, (key, extra)
        assert sc.columns_for(key, {"property_locations": _premises(("1", "1 Main St"))}) == \
            [dict(c) for c in d["columns"]]


def test_every_rating_basis_offered_prints_its_acord_letter():
    opts = next(c for c in sc.SCHEDULE_DEFS[GL]["columns"] if c["key"] == "premium_basis")["options"]
    letters = [ps.rating_basis_code(o) for o in opts]
    assert letters == ["P", "S", "C", "A", "M", "U", "T"]
    assert ps.rating_basis_code("Subcontractor Cost") == "C"           # Brent's own word
    assert ps._rejects_misplaced_rating_basis(
        "GeneralLiabilityLineOfBusiness_TypeOfWorkSubcontractedDescription_A", "Subcontractor Cost")


def test_the_window_shows_only_gl_own_rows_and_keeps_their_stored_positions():
    """ADVERSARIAL: a WC class filed under GL and the carrier's policy-level
    line are not classifications to confirm ("do not substitute WC class codes
    for GL codes")."""
    facts = _wc_misfiled()
    facts[GL] = [facts[GL][0],
                 _row(location="Location 000", classification="Fungi Or Bacteria Exclusion",
                      exposure_amount="($33)"),
                 _row(location="Location 1", class_code="91580", premium_basis="Payroll",
                      exposure_amount="$39,300")]
    rows = sc.rows_from_facts(GL, facts)
    assert [r["class_code"] for r in rows] == ["91580"]
    assert rows[0][sc.ROW_ID_KEY] == "#2"


def test_the_window_opens_with_the_codes_the_package_already_holds():
    facts = {"gl_class_codes_by_location": [{"location": "Loc 1", "codes": ["92478", "91580"]}]}
    rows = sc.rows_from_facts(GL, facts)
    assert [(r["location"], r["class_code"]) for r in rows] == [("Loc 1", "92478"), ("Loc 1", "91580")]
    assert all(sc.ROW_ID_KEY not in r for r in rows)            # new rows on save
    # never seeded over the table's own rows, never a ZIP or another line's code
    facts[GL] = [_row(class_code="11111")]
    assert [r["class_code"] for r in sc.rows_from_facts(GL, facts)] == ["11111"]
    assert sc.rows_from_facts(GL, {"gl_class_codes_by_location": "Denver CO 80216"}) == []
    wc = _wc_misfiled()
    wc.pop(GL)
    wc["gl_class_codes_by_location"] = "5190"
    assert sc.rows_from_facts(GL, wc) == []


@pytest.mark.parametrize("typed", ["unknown", "TBD", "N/A", "not sure", "need to check", "?", "--"])
def test_a_typed_non_answer_is_the_follow_up_mark_never_a_code(typed):
    rows, _rep = sc.validate_rows(GL, [{"location": "Location 1", "class_code": typed,
                                       "premium_basis": "Payroll", "exposure_amount": "1000"}])
    assert rows[0]["class_code"] == "" and rows[0][sc.FOLLOW_UP_KEY] is True
    facts = {GL: sc.rows_for_facts(GL, rows)}
    assert not sq.gl_class_codes_present(facts)                         # a gap, not an answer
    assert GL_CODES in _soft(facts)


def test_prose_is_never_read_as_a_non_answer():
    """ADVERSARIAL: "waiting" / "later" are uncertainty words, and a
    classification is prose - only a placeholder token clears a description."""
    rows, _ = sc.validate_rows(GL, [{"classification": "Waiting room services", "class_code": "91580"},
                                    {"classification": "Later-stage finish carpentry", "class_code": "91341"}])
    assert [r["classification"] for r in rows] == ["Waiting room services", "Later-stage finish carpentry"]
    assert not any(r.get(sc.FOLLOW_UP_KEY) for r in rows)


def test_the_mark_rides_on_a_row_and_an_empty_row_is_still_dropped():
    rows, _ = sc.validate_rows(GL, [{"location": "Location 1", sc.FOLLOW_UP_KEY: True},
                                    {sc.FOLLOW_UP_KEY: True},
                                    {"class_code": "unknown"}])
    assert rows == [{"location": "Location 1", "classification": "", "class_code": "",
                     "premium_basis": "", "exposure_amount": "", sc.FOLLOW_UP_KEY: True}]
    assert sc.validate_rows(GL, [{"location": "x", sc.FOLLOW_UP_KEY: "yes"}])[0][0][sc.FOLLOW_UP_KEY]
    # a table that does not declare the mark never carries it
    assert sc.FOLLOW_UP_KEY not in sc.validate_rows("auto_drivers", [{"name": "Jo", "follow_up": True}])[0][0]


def test_a_basis_choice_is_kept_and_a_shrug_in_it_is_the_mark():
    rows, _ = sc.validate_rows(GL, [{"class_code": "91580", "premium_basis": "Other", "exposure_amount": "5"},
                                    {"class_code": "91581", "premium_basis": "not sure", "exposure_amount": "5"}])
    assert rows[0]["premium_basis"] == "Other" and sc.FOLLOW_UP_KEY not in rows[0]
    assert rows[1]["premium_basis"] == "" and rows[1][sc.FOLLOW_UP_KEY] is True


def test_the_mark_survives_the_round_trip_through_the_window():
    facts = {GL: [_row(location="Location 1", class_code="91580", follow_up=True), _row(class_code="91581")]}
    served = sc.validate_rows(GL, sc.rows_from_facts(GL, facts))[0]
    assert served[0][sc.FOLLOW_UP_KEY] is True and sc.FOLLOW_UP_KEY not in served[1]
    again = sc.merge_saved_rows(GL, facts[GL], served, source="producer", facts=facts)
    assert again == facts[GL]                                   # an untouched save changes nothing


def test_a_stale_id_pointing_at_a_hidden_row_never_claims_it():
    facts = _wc_misfiled()
    facts[GL] = [facts[GL][0], _row(class_code="91580", location="Location 1")]
    stale = sc.validate_rows(GL, [{sc.ROW_ID_KEY: "#0", "class_code": "92478", "location": "Location 2"}])[0]
    out = sc.merge_saved_rows(GL, facts[GL], stale, source="producer", facts=facts)
    assert out[-1] == facts[GL][0] and out[0]["class_code"] == "92478" and len(out) == 2


@pytest.mark.parametrize("code, ok", [("91580", True), ("GL 91580", True), ("5190", True),
                                      ("Electrical", False), ("12", False)])
def test_the_code_cell_takes_a_number(code, ok):
    col = next(c for c in sc.SCHEDULE_DEFS[GL]["columns"] if c["key"] == "class_code")
    assert (sc.validate_cell(col, code) == "") is ok


def test_a_save_merges_by_row_and_keeps_what_the_window_does_not_show():
    facts = _wc_misfiled()
    facts[GL] = [facts[GL][0],
                 _row(location="Location 1", class_code="91580", classification="Carpentry",
                      premium_basis="Payroll", exposure_amount="39,300", territory="104",
                      subcontractor_pct="10%")]
    shown = sc.validate_rows(GL, sc.rows_from_facts(GL, facts))[0]
    assert [r["class_code"] for r in shown] == ["91580"]
    shown[0]["exposure_amount"] = "45,000"
    shown[0][sc.FOLLOW_UP_KEY] = True
    shown.append({"location": "Location 1", "class_code": "92478", "premium_basis": "Gross Sales",
                  "exposure_amount": "2,000,000"})
    typed = sc.validate_rows(GL, shown)[0]
    out = sc.merge_saved_rows(GL, facts[GL], typed, source="producer", facts=facts)
    assert out[0]["exposure_amount"] == "45,000" and out[0]["territory"] == "104"
    assert out[0]["subcontractor_pct"] == "10%" and out[0][sc.FOLLOW_UP_KEY] is True
    assert out[1]["class_code"] == "92478" and "territory" not in out[1]
    assert out[2] == facts[GL][0]                                       # the WC row, untouched
    # unticking clears the mark; deleting the row deletes it (the WC row stays)
    again = sc.validate_rows(GL, [dict(sc.rows_from_facts(GL, {**facts, GL: out})[0],
                                       **{sc.FOLLOW_UP_KEY: False})])[0]
    out2 = sc.merge_saved_rows(GL, out, again, source="producer", facts={**facts, GL: out})
    assert sc.FOLLOW_UP_KEY not in out2[0] and len(out2) == 2 and out2[1] == facts[GL][0]


def test_location_and_classification_choices_are_the_packages_own():
    facts = {
        "property_locations": _premises(("1", "4800 Dahlia St"), ("2", "1245 Industrial Blvd"))
        + [dict(_premises(("1", "4800 Dahlia St"))[0], building_number="2")]
        + [dict(_premises(("A", "9 Side St"))[0])],
        "operations_description": "Electrical contracting - commercial and residential",
        GL: [_row(classification="Electrical Work - Within Buildings", class_code="92478"),
             _row(classification="N/A", class_code="91580")],
    }
    facts.update({"wc_class_codes": _wc_misfiled()["wc_class_codes"]})
    facts[GL].append(_wc_misfiled()[GL][0])
    cols = {c["key"]: c for c in sc.columns_for(GL, facts)}
    assert cols["location"]["options"] == [
        "Location 1 - 4800 Dahlia St, Denver, CO 80216",
        "Location 2 - 1245 Industrial Blvd, Denver, CO 80216",
        "9 Side St, Denver, CO 80216"]                         # one per premises; a non-digit number -> address
    assert cols["classification"]["options"] == [
        "Electrical Work - Within Buildings",
        "Electrical contracting - commercial and residential"]  # no placeholder, no WC description
    assert cols["class_code"]["refused"] == ["5190"]
    # each location choice prints that premises' LOC #
    for label, want in zip(cols["location"]["options"][:2], ("1", "2")):
        assert ps._hazard_location_number(label, facts) == want
    # a long operations narrative is typed, not offered
    facts["operations_description"] = "x " * 120
    assert len({c["key"]: c for c in sc.columns_for(GL, facts)}["classification"]["options"]) == 1


@pytest.mark.parametrize("facts", [None, {}, {GL: None}, {GL: "garbage"}, {GL: [None, "91580", 7]},
                                   {"property_locations": "x", "locations": ["1 Main St", None]}])
def test_malformed_shapes_never_raise(facts):
    rows = sc.rows_from_facts(GL, facts or {})
    assert isinstance(rows, list)
    assert isinstance(sc.columns_for(GL, facts), list)
    sc.merge_saved_rows(GL, (facts or {}).get(GL), sc.validate_rows(GL, rows)[0], facts=facts)


def test_many_classifications_are_kept_past_the_three_printed_rows():
    rows = [{"location": "Location 1", "class_code": str(91000 + n), "premium_basis": "Payroll",
             "exposure_amount": "100"} for n in range(5)]
    clean, report = sc.validate_rows(GL, rows)
    assert len(clean) == 5 and report["overflow"] == 2
    facts = {GL: sc.rows_for_facts(GL, clean)}
    assert sq.gl_class_codes_present(facts) and not _soft(facts)
    assert ps._resolve_gl_hazard_row("GeneralLiability_Hazard_ClassCode_C", facts) == "91002"


# ═════════════════════════════════════════════════════════════════════════════
# 3. Both cards open the window; the review shows ONE GL item
# ═════════════════════════════════════════════════════════════════════════════

def test_both_gl_rules_open_the_table_under_brents_title():
    for msg, code in ((GL_CODES, "legacy_gl_no_class_codes"),
                      (GL_EXPOSURE, "legacy_gl_no_exposure_basis")):
        got_code, cluster, tier = IR.classify_legacy(msg, "soft_warning")
        assert got_code == code and cluster == IR.GL_WINDOW_CLUSTER and tier == "recommended"
        assert IR.resolution_for(code) == {"mode": "schedule", "schedule_key": GL}
        assert IR._legacy_message_resolution(msg)["schedule_key"] == GL
    assert "WC" not in IR.GL_WINDOW_CLUSTER and "Workers" not in IR.GL_WINDOW_CLUSTER


def test_a_card_on_the_old_fact_opens_the_table_but_the_typed_door_still_writes():
    assert AR.answer_mode("gl_class_codes_by_location", {}) == {
        "mode": "schedule", "fact": GL, "schedule_key": GL}
    assert AR.answer_mode(GL, {})["mode"] == "schedule"
    # back-compat: a typed answer (the ARQ text question, an older tab) still lands
    assert AR.can_write_scalar("gl_class_codes_by_location", {}) is True
    # nothing else moved: the revenue / payroll facts stay typed boxes
    assert AR.answer_mode("total_revenue", {})["mode"] == "field"
    assert AR.answer_mode("total_payroll", {})["mode"] == "field"


def _gl_items(view):
    return [it for tier in view["warnings"].values() for c in tier for it in c["items"]
            if c["cluster"] == IR.GL_WINDOW_CLUSTER]


@pytest.mark.parametrize("order", [(GL_CODES, GL_EXPOSURE), (GL_EXPOSURE, GL_CODES)])
def test_both_warnings_are_one_item_whatever_their_order(order):
    view = IR.build_grouped_view(IR.build_structured_from_sources(legacy_soft=list(order)), [], list(order))
    items = _gl_items(view)
    assert len(items) == 1 and view["counts"]["warnings"] == 1
    it = items[0]
    assert it["code"] == "legacy_gl_no_class_codes"                      # the first in the table's order
    assert it["issue_id"] == IR.review_item_id(GL)
    assert it["message"] == sc.SCHEDULE_DEFS[GL]["review_item"]
    assert it["resolution"] == {"mode": "schedule", "schedule_key": GL}
    assert {f["code"] for f in it["folded"]} == {"legacy_gl_no_class_codes", "legacy_gl_no_exposure_basis"}


@pytest.mark.parametrize("msg, code", [(GL_CODES, "legacy_gl_no_class_codes"),
                                       (GL_EXPOSURE, "legacy_gl_no_exposure_basis")])
def test_one_part_left_keeps_its_own_words_and_the_items_one_id(msg, code):
    view = IR.build_grouped_view(IR.build_structured_from_sources(legacy_soft=[msg]), [], [msg])
    (it,) = _gl_items(view)
    assert it["message"] == msg and it["code"] == code
    assert it["issue_id"] == IR.review_item_id(GL)        # a dismissal stays with the item


def test_a_session_stored_with_the_old_boxes_opens_and_folds_the_window():
    old = [
        {"code": "legacy_gl_no_class_codes", "severity": "soft_warning", "message": GL_CODES, "forms": [],
         "cluster": "GL class code alignment", "tier": "recommended",
         "resolution": {"mode": "field", "facts": ["gl_class_codes_by_location"]}},
        {"code": "legacy_gl_no_exposure_basis", "severity": "soft_warning", "message": GL_EXPOSURE,
         "forms": [], "cluster": "GL exposure basis", "tier": "recommended",
         "resolution": {"mode": "field", "facts": ["total_revenue", "total_payroll"]}},
    ]
    view = IR.build_grouped_view(copy.deepcopy(old), [], [GL_CODES, GL_EXPOSURE])
    (it,) = _gl_items(view)
    assert it["resolution"]["mode"] == "schedule"
    clusters = {c["cluster"] for t in view["warnings"].values() for c in t}
    assert clusters == {IR.GL_WINDOW_CLUSTER}
    from services.arq_service import _schedules_offered_by_issues
    assert GL in _schedules_offered_by_issues({"structured_issues": old})


def test_the_fold_reaches_no_other_table_and_no_other_section():
    """ADVERSARIAL: two items opening another WHOLE table stay two; a GL item
    promoted to a blocker is never folded under a warning."""
    drivers = [IR.make_issue("legacy_x1", "soft_warning", "Driver schedule A", cluster="Auto", tier="recommended"),
               IR.make_issue("legacy_x2", "soft_warning", "Driver schedule B", cluster="Auto", tier="recommended")]
    for d in drivers:
        d["resolution"] = {"mode": "schedule", "schedule_key": "auto_drivers"}
    view = IR.build_grouped_view(drivers, [], ["Driver schedule A", "Driver schedule B"])
    assert view["counts"]["warnings"] == 2
    structured = IR.build_structured_from_sources(legacy_soft=[GL_CODES, GL_EXPOSURE])
    view = IR.build_grouped_view(structured, [], [GL_CODES, GL_EXPOSURE],
                                 promote_codes=["legacy_gl_no_exposure_basis"])
    assert view["counts"] == {"hard_stops": 1, "warnings": 1}
    assert IR.review_item_table({"mode": "schedule", "schedule_key": GL, "columns": ["x"]}) is None
    assert IR.review_item_table({"mode": "schedule", "schedule_key": GL, "facts": ["x"]}) is None
    assert IR.review_item_table({"mode": "field", "facts": [GL]}) is None


def test_the_screen_points_of_both_rules_sit_on_the_one_card():
    assert IR.fold_card_codes(["legacy_gl_no_exposure_basis", "legacy_gl_no_class_codes", "x"]) == {
        "legacy_gl_no_exposure_basis": "legacy_gl_no_class_codes",
        "legacy_gl_no_class_codes": "legacy_gl_no_class_codes"}
    assert IR.fold_card_codes(["legacy_gl_no_exposure_basis"]) == {}     # one rule: drawn as itself
    assert IR.fold_card_codes([]) == {} and IR.fold_card_codes(None) == {}


def test_the_download_screen_folds_the_gl_card_into_the_gl_item():
    from services import needs_attention as na
    view = IR.build_grouped_view(IR.build_structured_from_sources(legacy_soft=[GL_CODES, GL_EXPOSURE]),
                                 [], [GL_CODES, GL_EXPOSURE])
    rows = na.review_issue_rows([view])
    assert len(rows) == 1 and rows[0]["fix_facts"] == [GL]
    card = {"rec_id": "rec_gl_class_codes", "field": "gl_class_codes_by_location"}
    assert na.card_fix_keys(card) & set(rows[0]["fix_facts"])
    assert na.box_fold_keys("GeneralLiability_Hazard_Exposure_B") == [GL]


def test_current_issue_resolution_leaves_every_other_card_alone():
    per_building = {"code": "minimum_viable_cope_missing",
                    "resolution": {"mode": "schedule", "schedule_key": "property_locations",
                                   "per_building": True, "columns": ["occupancy_type"]}}
    assert IR.current_issue_resolution(per_building) == per_building["resolution"]
    assert IR.current_issue_resolution({"code": "legacy_gl_no_class_codes",
                                        "resolution": {"mode": "field", "facts": ["x"]}})["mode"] == "schedule"
    assert IR.current_issue_resolution(None) is None


# ═════════════════════════════════════════════════════════════════════════════
# 4. The score reads the window's rows
# ═════════════════════════════════════════════════════════════════════════════

def test_filling_the_window_clears_both_gl_warnings():
    assert set(_soft({})) == {GL_CODES, GL_EXPOSURE}
    rows = sc.validate_rows(GL, [{"location": "Location 1", "classification": "Electrical contracting",
                                  "class_code": "92478", "premium_basis": "Payroll",
                                  "exposure_amount": "1400000"}])[0]
    facts = {GL: sc.rows_for_facts(GL, rows)}
    assert _soft(facts) == []
    # never an estimate of the package's totals from GL rows
    assert "total_revenue" not in facts and "total_payroll" not in facts


def test_each_part_of_the_window_answers_its_own_warning():
    code_only = {GL: [_row(location="Location 1", class_code="92478")]}
    assert _soft(code_only) == [GL_EXPOSURE]
    exposure_only = {GL: [_row(location="Location 1", premium_basis="Gross Sales",
                               exposure_amount="$3,000,000", follow_up=True)]}
    assert _soft(exposure_only) == [GL_CODES]                # an unknown code stays a gap


@pytest.mark.parametrize("basis, exposure, counts", [
    ("Payroll", "1,400,000", True), ("Area", "8,500", True), ("N/A", "1,000", False),
    ("unknown", "1,000", False), ("Payroll", "TBD", False), ("", "1,000", False)])
def test_the_exposure_reader_wants_a_stated_basis_and_an_amount(basis, exposure, counts):
    facts = {GL: [_row(class_code="92478", premium_basis=basis, exposure_amount=exposure)]}
    assert sq._dec_entries_state_payroll(facts) is counts


def test_a_workers_comp_row_filed_under_gl_answers_neither_gl_warning():
    """ADVERSARIAL - "Do not substitute WC class codes for GL codes" (Brent).
    The WC class's payroll used to silence the GL exposure warning."""
    facts = _wc_misfiled()
    assert not sq.gl_class_codes_present(facts)
    assert not sq._dec_entries_state_payroll(facts)
    assert set(_soft(facts)) == {GL_CODES, GL_EXPOSURE}
    # ...while a five-digit GL code the WC table repeats (a misfile the other way)
    # stays GL's for the grid, the window and the exposure reader (the shape rule,
    # `pdf_service._gl_row_is_another_lines`). The class-code reader follows the
    # same rule since 22 Oct 2026 (the Z14 open end, closed by build 23).
    facts[GL][0]["class_code"] = "91580"
    facts["wc_class_codes"][0]["code"] = "91580"
    assert sq._dec_entries_state_payroll(facts)
    assert [r["class_code"] for r in sc.rows_from_facts(GL, facts)] == ["91580"]
    assert sq.gl_class_codes_present(facts)


def test_the_acord_126_card_asks_the_one_reader():
    facts = {GL: [_row(location="Location 1", classification="Unknown work", follow_up=True)],
             "gl_limits": "$1,000,000", "operations_description": "Electrical"}
    res = sq.calculate_sqs(facts, GLF, {}, _schema("ACORD_126"), ["ACORD_126"], [], [], 0,
                           form_id="ACORD_126")
    recs = {r.get("rec_id"): r for r in res.get("recommendations") or [] if isinstance(r, dict)}
    assert "rec_gl_class_codes" in recs                     # a row without a code is not a code
    assert recs["rec_gl_class_codes"]["answer_mode"] == "schedule"
    facts[GL][0]["class_code"] = "92478"
    res = sq.calculate_sqs(facts, GLF, {}, _schema("ACORD_126"), ["ACORD_126"], [], [], 0,
                           form_id="ACORD_126")
    assert "rec_gl_class_codes" not in {r.get("rec_id") for r in res.get("recommendations") or []}


# ═════════════════════════════════════════════════════════════════════════════
# 5. After forms: the save reaches the forms through the stamper's own doors
# ═════════════════════════════════════════════════════════════════════════════

def _generated_126(field_state=None, confidence=None):
    return {"ACORD_126": {"schema": _schema("ACORD_126"), "field_state": dict(field_state or {}),
                          "confidence": dict(confidence or {}), "client_filled_fields": []}}


def test_a_save_after_forms_stamps_letters_and_numbers_never_the_raw_cells():
    from services.arq_service import _restamp_schedule_into_forms
    before = {"property_locations": _premises(("1", "4800 Dahlia St")),
              GL: [_row(location="Location 1", class_code="91580")]}
    after = copy.deepcopy(before)
    after[GL][0].update(premium_basis="Payroll", exposure_amount="39,300",
                        classification="Carpentry")
    gen = _generated_126({"GeneralLiability_Hazard_ClassCode_A": "91580",
                          "GeneralLiability_Hazard_Exposure_A": "$1,000",      # an AI guess
                          "GeneralLiability_Hazard_LocationProducerIdentifier_A": "1"},
                         {"GeneralLiability_Hazard_Exposure_A": "low_confidence"})
    touched = _restamp_schedule_into_forms(gen, GL, after, facts_before=before, provenance="producer")
    st, conf = gen["ACORD_126"]["field_state"], gen["ACORD_126"]["confidence"]
    assert touched == ["ACORD_126"]
    assert st["GeneralLiability_Hazard_PremiumBasisCode_A"] == "P"
    assert st["GeneralLiability_Hazard_Exposure_A"] == "39,300"
    assert st["GeneralLiability_Hazard_Classification_A"] == "Carpentry"
    assert conf["GeneralLiability_Hazard_Exposure_A"] == "producer"
    assert st["GeneralLiability_Hazard_LocationProducerIdentifier_A"] == "1"      # did not move


def test_a_cell_the_save_did_not_move_keeps_what_the_form_shows():
    from services.arq_service import _restamp_schedule_into_forms
    before = {GL: [_row(location="Location 1", class_code="91580")]}
    after = copy.deepcopy(before)
    after[GL][0]["classification"] = "Carpentry"
    gen = _generated_126({"GeneralLiability_Hazard_PremiumBasisCode_A": "P"},
                         {"GeneralLiability_Hazard_PremiumBasisCode_A": "ai_verified"})
    _restamp_schedule_into_forms(gen, GL, after, facts_before=before, provenance="producer")
    assert gen["ACORD_126"]["field_state"]["GeneralLiability_Hazard_PremiumBasisCode_A"] == "P"
    # ...and a value the person cleared clears its box
    cleared = copy.deepcopy(after)
    cleared[GL][0]["class_code"] = None
    gen2 = _generated_126({"GeneralLiability_Hazard_ClassCode_A": "91580"},
                          {"GeneralLiability_Hazard_ClassCode_A": "producer"})
    _restamp_schedule_into_forms(gen2, GL, cleared, facts_before=after, provenance="producer")
    assert gen2["ACORD_126"]["field_state"]["GeneralLiability_Hazard_ClassCode_A"] == ""


def test_the_125_gl_code_takes_the_persons_window_over_the_ais_reading():
    facts = {"applicant_gl_class_code": {"value": "91340", "source": "ai_high", "confidence": "ai_high"},
             GL: [_row(location="Location 1", class_code="92478", premium_basis="Payroll",
                       exposure_amount="100")]}
    box = "NamedInsured_GeneralLiabilityCode_A"
    assert ps._resolve_applicant_row_a_scalar(box, facts) == "91340"     # documents' rows: unchanged
    sc.mark_human_rows(facts, GL, "producer")
    assert ps._resolve_applicant_row_a_scalar(box, facts) == "92478"     # the person's window
    facts["applicant_gl_class_code"]["source"] = "producer"
    assert ps._resolve_applicant_row_a_scalar(box, facts) == "91340"     # a person's stated code stands
    facts["applicant_gl_class_code"]["source"] = "ai_high"
    facts[GL] = [_row(class_code=str(91000 + n)) for n in range(4)]      # more than the box shows
    sc.mark_human_rows(facts, GL, "producer")
    assert ps._resolve_applicant_row_a_scalar(box, facts) == "91340"


def test_the_save_restamps_the_boxes_derived_from_the_rows():
    from services.arq_service import _restamp_boxes_the_answer_decides
    assert sc.SCHEDULE_DEFS[GL].get("restamp_derived") is True
    before = {"applicant_name": "Choice Electric LLC"}
    after = dict(before, **{GL: [_row(location="Location 1", class_code="92478")]})
    gen = {"ACORD_125": {"schema": _schema("ACORD_125"), "field_state": {}, "confidence": {},
                         "client_filled_fields": []}}
    touched = _restamp_boxes_the_answer_decides(gen, before, after, [GL], None, "producer")
    assert "ACORD_125" in touched
    assert gen["ACORD_125"]["field_state"]["NamedInsured_GeneralLiabilityCode_A"] == "92478"


# ═════════════════════════════════════════════════════════════════════════════
# 6. Frontend - the table's cells, and the page folds the GL row into the card
# ═════════════════════════════════════════════════════════════════════════════

def _node(tmp_path, body, *modules):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    imports = "".join(f"import * as {alias} from {json.dumps((FRONT / 'utils' / mod).as_uri())};\n"
                      for alias, mod in modules)
    script = tmp_path / "check.mjs"
    script.write_text(imports + body + "\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_the_cells_offer_choices_units_and_the_follow_up_mark(tmp_path):
    cols = json.dumps(sc.columns_for(GL, {"property_locations": _premises(("1", "4800 Dahlia St"))}))
    out = _node(tmp_path, f"""
const cols = {cols};
const by = Object.fromEntries(cols.map((c) => [c.key, c]));
const exp = by.exposure_amount;
console.log(JSON.stringify({{
  loc: C.cellOptions(by.location),
  basis: C.cellOptions(by.premium_basis),
  dup: C.cellOptions({{options: ["A", "a", " A ", "", null, "B"]}}),
  units: ["Payroll", "Gross Sales", "Total Cost", "Area", "Admissions", "Units", "Other", "", "p"]
    .map((b) => C.unitFor(exp, {{premium_basis: b}})),
  none: C.unitFor(by.location, {{premium_basis: "Payroll"}}),
  on: C.isFollowUp(C.withFollowUp({{a: 1}}, true)),
  off: C.withFollowUp({{a: 1, follow_up: true}}, false),
  key: C.FOLLOW_UP_KEY,
  codeErr: [S.validateCell(by.class_code, "Electrical"), S.validateCell(by.class_code, "91580")],
  refused: S.validateCell({{...by.class_code, refused: ["5190"], refused_message: "no"}}, " 5190 "),
}}));
""", ("C", "scheduleCells.js"), ("S", "scheduleImport.js"))
    assert out["loc"] == ["Location 1 - 4800 Dahlia St, Denver, CO 80216"]
    assert out["basis"] == list(sc.GL_RATING_BASES)
    assert out["dup"] == ["A", "B"]
    assert out["units"] == ["$", "$", "$", "sq ft", "admissions", "units", "", "", "$"]
    assert out["none"] == "" and out["on"] is True and out["off"] == {"a": 1}
    assert out["key"] == sc.FOLLOW_UP_KEY == ps._ROW_FOLLOW_UP_KEY
    assert out["codeErr"][0] and out["codeErr"][1] == ""
    assert out["refused"] == "no"


def test_the_page_lists_one_gl_item_and_the_card_carries_the_rows_points(tmp_path):
    view = IR.build_grouped_view(IR.build_structured_from_sources(legacy_soft=[GL_CODES, GL_EXPOSURE]),
                                 [], [GL_CODES, GL_EXPOSURE])
    row = AR.stamp_recommendation({"pillar": "structural_completeness", "field": "gl_class_codes_by_location",
                                   "action": "GL class codes", "answer_gain": 6, "answer_gain_is_exact": True,
                                   "answer_gain_share": True})
    from services.review_recommendations import with_fix_routes
    pkg = with_fix_routes({"top_recommendations": [row], "screen_shares": {"gl_class_codes_by_location": [6, True]},
                           "screen_card_points": {"legacy_gl_no_class_codes": [3, False]}}, {})
    out = _node(tmp_path, f"""
const view = {json.dumps(view)};
const pkg = {json.dumps(pkg)};
const covered = R.onScreenFixKeys(view, null);
const pts = P.screenPoints(pkg, view, null);
console.log(JSON.stringify({{
  covered: [...covered],
  listed: R.scoreItems(pkg, covered).length,
  alone: R.scoreItems(pkg, new Set()).length,
  card: pts.cards.get("legacy_gl_no_class_codes") || null,
  orphan: pts.unanswerable,
}}));
""", ("R", "recommendations.js"), ("P", "screenPoints.js"))
    assert out["covered"] == [f"table:{GL}"]
    assert out["listed"] == 0 and out["alone"] == 1       # hidden only because the card asks it
    assert out["card"]["points"] == 9 and not out["orphan"]


def test_the_window_passes_the_mark_and_shows_its_heading():
    table = (FRONT / "components" / "arq" / "ScheduleTable.jsx").read_text(encoding="utf-8")
    modal = (FRONT / "components" / "form" / "ResolutionModal.jsx").read_text(encoding="utf-8")
    assert "followUp = false" in table and "<datalist" in table and "list={hasList" in table
    assert "followUp={schedule.follow_up === true}" in modal
    assert "schedule.title" in modal and "schedule.intro" in modal
    for text in (table, modal, (FRONT / "utils" / "scheduleCells.js").read_text(encoding="utf-8")):
        assert "—" not in text


# ═════════════════════════════════════════════════════════════════════════════
# 7. Review fixes (21 Oct 2026 evening) - each finding, adversarial case first
# ═════════════════════════════════════════════════════════════════════════════

ROOFER = "Roofing contractor installing commercial roofs"


def _save(facts: dict, rows: list) -> dict:
    """A producer save through the ONE write door (`_write_schedule_rows`),
    validated as the save path validates (`shown` = the table as served)."""
    from services.arq_service import _write_schedule_rows
    clean, _ = sc.validate_rows(GL, rows, shown=sc.rows_from_facts(GL, facts))
    _write_schedule_rows(facts, GL, clean, "producer")
    return facts


def _mismatch_items(facts):
    return [i for i in sq.exposure_deduction_items(facts, GLF, [], [])
            if i.get("fact") == "gl_class_codes_by_location"]


# ── High: the -15 "class codes that match the operations" row ───────────────

def test_the_mismatch_row_opens_the_window_and_the_window_clears_it():
    facts = {"operations_description": ROOFER, "gl_class_codes_by_location": ["9079"]}
    (item,) = _mismatch_items(facts)
    assert item["points"] == 15 and item["kind"] == "conflict"
    rec = AR.stamp_recommendation({"field": item["fact"], "rec_id": "x"}, facts)
    assert rec["answer_mode"] == "schedule" and rec["schedule_key"] == GL
    _save(facts, [{"location": "Location 1", "classification": "Roofing", "class_code": "98677",
                   "premium_basis": "Payroll", "exposure_amount": "100000"}])
    assert _mismatch_items(facts) == []
    assert sq.gl_class_codes(facts) == ["98677"]           # the stale 9079 is not the answer
    assert facts["gl_class_codes_by_location"] == ["9079"]   # ...and is never overwritten


def test_a_persons_code_is_judged_never_exempted():
    """ADVERSARIAL: the person's answer outranks the stale home, it is not a
    pass - a restaurant code typed for a roofer is still the mismatch."""
    facts = {"operations_description": ROOFER}
    assert _mismatch_items(facts) == [] or _mismatch_items(facts)[0]["kind"] != "conflict"
    _save(facts, [{"location": "Location 1", "class_code": "9079", "premium_basis": "Payroll",
                   "exposure_amount": "1"}])
    (item,) = _mismatch_items(facts)
    assert item["points"] == 15 and item["kind"] == "conflict"


def test_an_unknown_code_or_no_save_leaves_the_documents_reading():
    facts = {"operations_description": ROOFER, "gl_class_codes_by_location": ["9079"]}
    _save(facts, [{"location": "Location 1", "class_code": "unknown", "premium_basis": "Payroll",
                   "exposure_amount": "1000"}])
    assert sq.person_gl_class_codes(facts) == []           # an unknown code answers nothing
    assert _mismatch_items(facts)[0]["points"] == 15
    plain = {"operations_description": ROOFER, "gl_class_codes_by_location": ["9079"],
             GL: [_row(class_code="98677")]}               # the documents' rows, no person
    assert sq.person_gl_class_codes(plain) == []
    assert _mismatch_items(plain)[0]["points"] == 15       # today's reading, unchanged


def test_a_table_rewritten_after_the_save_is_no_longer_the_persons():
    facts = {"operations_description": ROOFER, "gl_class_codes_by_location": ["9079"]}
    _save(facts, [{"location": "Location 1", "class_code": "98677"}])
    assert sq.person_gl_class_codes(facts) == ["98677"]
    facts[GL] = facts[GL] + [_row(class_code="91580")]     # a document re-merge wrote on it
    assert sq.person_gl_class_codes(facts) == []
    assert _mismatch_items(facts)[0]["points"] == 15


def test_a_corrected_seed_is_the_code_every_reader_sees():
    facts = {"gl_class_codes_by_location": [{"location": "Location 1", "codes": ["91580"]}]}
    (seed,) = sc.rows_from_facts(GL, facts)
    assert seed["class_code"] == "91580"
    _save(facts, [dict(seed, class_code="92478")])
    assert sq.gl_class_codes(facts) == ["92478"]
    assert ps._person_gl_codes(facts, "applicant_gl_class_code") == "92478"
    assert [r["class_code"] for r in ps._gl_hazard_rows(facts)] == ["92478"]


@pytest.mark.parametrize("facts", [None, {}, {GL: "junk"}, {GL: [None, 3]},
                                   {GL: [{"class_code": "91580"}], "_human_schedules": "x"},
                                   {"_human_schedules": {GL: {"fingerprint": "nope"}}, GL: [{}]}])
def test_the_person_reader_never_raises(facts):
    assert sq.person_gl_class_codes(facts) == []


# ── Low: a five-digit GL code a WC table repeats (the Z14 misfile) ──────────

def test_a_persons_gl_code_a_wc_table_repeats_answers_the_gap():
    wc = [{"code": "91580", "description": "Heating and Air Conditioning", "payroll": "100000",
           "state": "CO"}]
    documents = {"wc_class_codes": copy.deepcopy(wc), GL: [_row(class_code="91580")]}
    # The documents' own misfile counts too since 22 Oct 2026 (build 23 closed the
    # Z14 open end this line pinned): a five-digit GL code a WC table repeats is
    # GL's for the score as for the 126 (`pdf_service._gl_row_is_another_lines`).
    assert sq.gl_class_codes_present(documents)
    facts = {"wc_class_codes": copy.deepcopy(wc)}
    _save(facts, [{"location": "Location 1", "class_code": "91580", "premium_basis": "Payroll",
                   "exposure_amount": "100000"}])
    assert sq.gl_class_codes_present(facts)
    assert _soft(facts) == []


# ── Medium: "Open again" on the folded GL item ──────────────────────────────

def _still_live(monkeypatch, session: dict, issue_id) -> bool:
    import asyncio
    from routes import audit_routes as ar

    async def _get(_sid):
        return session
    monkeypatch.setattr(ar, "get_processing_session", _get)
    return asyncio.run(ar._issue_still_live("s1", issue_id))


@pytest.mark.parametrize("msgs", [[GL_CODES], [GL_EXPOSURE], [GL_CODES, GL_EXPOSURE]])
def test_the_folded_items_own_id_is_live_while_a_gl_rule_fires(monkeypatch, msgs):
    structured = IR.build_structured_from_sources(legacy_soft=list(msgs))
    view = IR.build_grouped_view(copy.deepcopy(structured), [], list(msgs))
    (item,) = _gl_items(view)
    assert _still_live(monkeypatch, {"structured_issues": structured}, item["issue_id"]) is True
    # the rule's own id still answers, as before
    own = IR.issue_id_for(msgs[0], [])
    assert _still_live(monkeypatch, {"structured_issues": structured}, own) is True


def test_the_folded_id_is_not_live_once_no_gl_rule_fires(monkeypatch):
    gl_id = IR.review_item_id(GL)
    other = IR.build_structured_from_sources(legacy_soft=["Driver schedule not provided"])
    assert _still_live(monkeypatch, {"structured_issues": other}, gl_id) is False
    assert _still_live(monkeypatch, {"structured_issues": []}, gl_id) is False
    assert _still_live(monkeypatch, {}, gl_id) is False
    assert _still_live(monkeypatch, {"structured_issues": other}, None) is False


def test_a_session_stored_with_the_old_boxes_is_live_under_the_items_id(monkeypatch):
    old = [{"code": "legacy_gl_no_class_codes", "severity": "soft_warning", "message": GL_CODES,
            "forms": [], "resolution": {"mode": "field", "facts": ["gl_class_codes_by_location"]}}]
    assert IR.review_item_id_of(old[0]) == IR.review_item_id(GL)
    assert _still_live(monkeypatch, {"structured_issues": old}, IR.review_item_id(GL)) is True


def test_no_other_issue_answers_to_a_review_item_id():
    drivers = {"code": "legacy_x", "resolution": {"mode": "schedule", "schedule_key": "auto_drivers"}}
    cols = {"code": "x", "resolution": {"mode": "schedule", "schedule_key": GL, "columns": ["class_code"]}}
    for issue in (drivers, cols, {"code": "x"}, None, "junk", {}):
        assert IR.review_item_id_of(issue) is None


# ── Low: another line's code is refused at the save, never stored hidden ────

def _wc_package():
    return {"wc_class_codes": [{"code": "5190", "description": "Electrical wiring", "payroll": "1",
                                "state": "CO"}]}


def test_another_lines_code_is_refused_with_the_cells_own_words():
    facts = _wc_package()
    clean, report = sc.validate_rows(GL, [{"location": "Location 1", "class_code": "5190",
                                           "premium_basis": "Payroll", "exposure_amount": "1000"}])
    assert report["errors"] == {}                           # the cell rules alone pass it
    assert sc.refused_rows(GL, clean, facts) == {"0": {"class_code": sc.GL_REFUSED_CODE_MESSAGE}}
    col = next(c for c in sc.columns_for(GL, facts) if c["key"] == "class_code")
    assert col["refused"] == ["5190"] and col["refused_message"] == sc.GL_REFUSED_CODE_MESSAGE


@pytest.mark.parametrize("code", ["91580", "GL 5190", "", "8810"])
def test_only_a_row_the_window_would_hide_is_refused(code):
    facts = _wc_package()
    rows = [{"location": "Location 1", "class_code": code, "premium_basis": "Payroll",
             "exposure_amount": "1000"}]
    assert sc.refused_rows(GL, rows, facts) == {}
    assert sc.refused_rows(GL, [], facts) == {} and sc.refused_rows(GL, None, facts) == {}
    assert sc.refused_rows("auto_drivers", [{"class_code": "5190"}], facts) == {}


def test_a_typed_policy_level_line_is_refused_too():
    rows = [{"location": "Location 0", "classification": "Fungi exclusion", "exposure_amount": "(33)"}]
    assert sc.refused_rows(GL, rows, {}) == {"0": {"row": sc._HIDDEN_ROW_MESSAGE}}


def test_the_save_refuses_and_stores_nothing(monkeypatch):
    import asyncio
    from repositories import session_repository as sr
    from services.arq_service import save_session_schedule
    stored = {"facts": _wc_package(), "generated_forms": {}}
    writes = []

    async def _get(_sid):
        return copy.deepcopy(stored)

    async def _upd(_sid, payload, **_kw):
        writes.append(payload)
    monkeypatch.setattr(sr, "get_processing_session", _get)
    monkeypatch.setattr(sr, "upd_processing_session", _upd)
    ok, out = asyncio.run(save_session_schedule("s1", GL, [
        {"location": "Location 1", "class_code": "92478"},
        {"location": "Location 1", "class_code": "5190", "exposure_amount": "1"}]))
    assert ok is False and writes == []
    assert out["message"] == f"Row 2: {sc.GL_REFUSED_CODE_MESSAGE}" and "1" in out["errors"]
    ok, out = asyncio.run(save_session_schedule("s1", GL, [{"location": "Location 1",
                                                             "class_code": "92478"}]))
    assert ok is True and len(writes) == 1
    assert [r["class_code"] for r in writes[0]["facts"][GL]] == ["92478"]


# ── Low: serving a stored placeholder never ticks the mark ──────────────────

def _placeholder_row():
    return {GL: [{"location": "Location 001", "classification": "Electrical work", "class_code": "92478",
                  "premium_basis": "N/A", "exposure_amount": "None", "territory": "005"}]}


def test_serving_a_document_placeholder_marks_nothing():
    facts = _placeholder_row()
    served = sc.rows_from_facts(GL, facts)
    rows, _ = sc.validate_rows(GL, served, shown=served)
    assert sc.FOLLOW_UP_KEY not in rows[0]
    assert rows[0]["premium_basis"] == "N/A" and rows[0]["exposure_amount"] == "None"


def test_saving_another_row_keeps_the_documents_cell_and_no_mark():
    facts = _placeholder_row()
    served = sc.rows_from_facts(GL, facts)
    _save(facts, served + [{"location": "Location 2", "class_code": "91580"}])
    first = facts[GL][0]
    assert first["premium_basis"] == "N/A" and first["exposure_amount"] == "None"
    assert sc.FOLLOW_UP_KEY not in first and first["territory"] == "005"
    assert ps._row_prints_only_what_it_states(first) is False   # gap fill still reads it


def test_a_cell_the_person_changes_to_unknown_is_still_the_mark():
    """ADVERSARIAL - the fix must not switch the person's own mark off."""
    facts = _placeholder_row()
    (served,) = sc.rows_from_facts(GL, facts)
    _save(facts, [dict(served, exposure_amount="not sure")])
    first = facts[GL][0]
    assert first.get(sc.FOLLOW_UP_KEY) is True and not first.get("exposure_amount")
    assert first["premium_basis"] == "N/A"                 # untouched cell kept
    # a new row, and no `shown` at all (a fresh import), behave as before
    new, _ = sc.validate_rows(GL, [{"location": "Location 3", "class_code": "TBD"}],
                              shown=sc.rows_from_facts(GL, facts))
    assert new[0]["class_code"] == "" and new[0][sc.FOLLOW_UP_KEY] is True
    bare, _ = sc.validate_rows(GL, [dict(served)])
    assert bare[0].get(sc.FOLLOW_UP_KEY) is True


def test_an_unchanged_seed_row_marks_nothing():
    facts = {"gl_class_codes_by_location": [{"location": "Unknown", "codes": ["91580"]}]}
    seeds = sc.rows_from_facts(GL, facts)
    rows, _ = sc.validate_rows(GL, seeds, shown=seeds)
    assert all(sc.FOLLOW_UP_KEY not in r for r in rows)


def test_the_served_table_carries_no_mark_nobody_ticked(monkeypatch):
    import asyncio
    from repositories import session_repository as sr
    from services.arq_service import get_session_schedules

    async def _get(_sid):
        return {"facts": _placeholder_row(), "generated_forms": {},
                "structured_issues": IR.build_structured_from_sources(legacy_soft=[GL_CODES])}
    monkeypatch.setattr(sr, "get_processing_session", _get)
    (entry,) = asyncio.run(get_session_schedules("s1", only_key=GL))
    assert entry["follow_up"] is True
    assert all(sc.FOLLOW_UP_KEY not in r for r in entry["rows"])
    assert entry["rows"][0]["premium_basis"] == "N/A"


# ── Low, kept by decision: any stated ACORD 126 basis answers the exposure
#    warning (an area-rated class has no revenue or payroll to give) ────────

@pytest.mark.parametrize("basis", list(sc.GL_RATING_BASES))
def test_every_acord_126_basis_with_an_amount_states_the_gl_exposure(basis):
    assert sq._dec_entries_state_payroll({GL: [_row(class_code="61217", premium_basis=basis,
                                                    exposure_amount="5,000")]}) is True
