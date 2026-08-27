"""V1 H3 - Workers Compensation Data Capture (client section 8), 2026-08-27.

The client: capture WC exposure at the employee-group level (8.1), keep every
supporting WC fact (8.2), and NEVER generate or recommend a WC class code (8.3).

Every test here drives the REAL code - the real ACORD 130 schema through
`compute_form_gaps`, the real schedule definitions, the real merge helper - so
a fixture cannot be easier than production (change quality bar, D22).
"""

import json
import os
import re

import pytest

from services import coverage_evidence as ce
from services import schedule_capture as sc

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCHEMA_130 = os.path.join(os.path.dirname(_HERE), "forms_schemas", "ACORD_130_schema.json")


@pytest.fixture(scope="module")
def schema130():
    with open(_SCHEMA_130, encoding="utf-8") as fh:
        return json.load(fh)


def _rows():
    """The client's own 8.1 example, plus the formatting a real dec page prints."""
    return [
        {"code": "8810 Clerical", "description": "", "state": "CO",
         "payroll": "$100,000", "rate": "0.20", "full_time_employees": "2"},
        {"code": "8742", "description": "Outside sales", "state": "CO",
         "payroll": "$180,000", "rate": "0.35", "full_time_employees": "3",
         "part_time_employees": "0"},
        {"code": "5551", "description": "Roofing installation", "state": "co",
         "payroll": "$520,000", "rate": "12.10", "full_time_employees": "8"},
    ]


def _gaps(schema, facts):
    import logging
    from services.pdf_service import compute_form_gaps
    logging.disable(logging.CRITICAL)
    try:
        return compute_form_gaps("ACORD_130", schema, facts)
    finally:
        logging.disable(logging.NOTSET)


# ── 8.1 the table exists, on the canonical fact, with the form's own columns ──

def test_employee_group_table_is_the_wc_class_codes_fact():
    """Principle 1: ONE canonical fact. The scorer, the 130 checklist, the
    class-code vote and the stamper all read `wc_class_codes` - so the table
    must be that key, not a second one."""
    defn = sc.get_def("wc_class_codes")
    assert defn is not None
    keys = [c["key"] for c in defn["columns"]]
    for wanted in ("description", "full_time_employees", "part_time_employees",
                   "payroll", "state", "code"):
        assert wanted in keys, wanted
    assert not defn.get("producer_only"), "the client answers the exposure part"


def test_class_code_and_rate_are_producer_only_columns():
    """Core principle 5 / client 8.3: the client is never asked to classify."""
    defn = sc.get_def("wc_class_codes")
    by_key = {c["key"]: c for c in defn["columns"]}
    assert by_key["code"]["producer_only"] is True
    assert by_key["rate"]["producer_only"] is True
    assert not by_key["payroll"].get("producer_only")
    assert not by_key["description"].get("producer_only")


def test_every_wc_column_is_bound_to_a_real_acord_130_field(schema130):
    """The schedule_capture guard, spelled out for the two new tables: a
    column with no real ACORD binding is data that silently disappears."""
    from services.pdf_service import _SCHED_ROW_RE, _SCHEDULE_REGISTRY
    live = {}
    for field in schema130:
        m = _SCHED_ROW_RE.match(field)
        if not m:
            continue
        defn = _SCHEDULE_REGISTRY.get(m.group(1))
        if defn is not None:
            live.setdefault(defn.list_key, set()).add(defn.sub_key)
    for list_key in ("wc_class_codes", "wc_officers"):
        for col in sc.get_def(list_key)["columns"]:
            assert col["key"] in live[list_key], f"{list_key}.{col['key']} unbound"


def test_officers_table_is_producer_only_with_four_rows():
    defn = sc.get_def("wc_officers")
    assert defn["producer_only"] is True
    assert sc.is_producer_only("wc_officers")
    assert not sc.is_producer_only("wc_class_codes")
    assert sc.capacity_for("wc_officers") == 4          # ACORD 130 prints A-D
    assert sc.capacity_for("wc_class_codes") == sc.ROW_CAPACITY
    assert sc.capacity_for("no_such_schedule") == sc.ROW_CAPACITY


def test_officer_overflow_counts_against_the_forms_four_rows():
    rows = [{"name": f"Officer {i}", "include_exclude": "Included"} for i in range(6)]
    _r, report = sc.validate_rows("wc_officers", rows)
    assert report["row_count"] == 6
    assert report["overflow"] == 2


def test_employee_counts_must_be_whole_numbers():
    col = {"key": "full_time_employees", "label": "Full-time", "type": "number"}
    assert sc.validate_cell(col, "8") == ""
    assert sc.validate_cell(col, "1,200") == ""
    assert sc.validate_cell(col, "") == ""                # optional
    assert "whole number" in sc.validate_cell(col, "eight")
    assert "whole number" in sc.validate_cell(col, "2.5")


# ── 8.1 the rows reach the ACORD 130 - every box the client's example fills ──

def test_client_example_stamps_code_duties_payroll_and_counts(schema130):
    facts = {"applicant_name": "Acme Roofing", "wc_payroll": "$800,000",
             "num_employees_full_time": "11", "wc_class_codes": _rows()}
    mapped, gaps, blanks = _gaps(schema130, facts)
    assert mapped["WorkersCompensation_RateClass_ClassificationCode_C"] == "5551"
    assert mapped["WorkersCompensation_RateClass_DutiesDescription_C"] == "Roofing installation"
    assert mapped["WorkersCompensation_RateClass_RemunerationAmount_C"] == "$520,000"
    assert mapped["WorkersCompensation_RateClass_FullTimeEmployeeCount_C"] == "8"
    assert mapped["WorkersCompensation_RateClass_FullTimeEmployeeCount_A"] == "2"
    assert mapped["WorkersCompensation_RateClass_PartTimeEmployeeCount_B"] == "0"
    # The company-wide headcount (11) must NEVER land in a per-group box.
    for k, v in mapped.items():
        if "RateClass_" in k and "EmployeeCount" in k:
            assert v != "11", k
    # And no per-group count box is left for the LLM to invent from that headcount.
    assert not [k for k in gaps if "RateClass_" in k and "EmployeeCount" in k]


def test_compound_code_cell_is_split_before_it_prints(schema130):
    """8.3 'normalize known formatting': "8810 Clerical" is a code AND its
    wording - the code box gets 8810, the duties box gets Clerical."""
    from services.extraction_service import derive_wc_facts_from_class_rows
    facts = {"wc_class_codes": _rows()}
    derive_wc_facts_from_class_rows(facts)
    assert facts["wc_class_codes"][0]["code"] == "8810"
    assert facts["wc_class_codes"][0]["description"] == "Clerical"
    mapped, _g, _b = _gaps(schema130, facts)
    assert mapped["WorkersCompensation_RateClass_ClassificationCode_A"] == "8810"
    assert mapped["WorkersCompensation_RateClass_DutiesDescription_A"] == "Clerical"


@pytest.mark.parametrize("cell,code,desc", [
    ("8810", "8810", None),                       # bare code untouched
    ("8810A", "8810A", None),                     # suffix untouched
    ("5551 - Roofing", "5551", "Roofing"),
    ("5551: Roofing installation", "5551", "Roofing installation"),
    ("Roofing", "Roofing", None),                 # no code shape -> untouched
    ("", "", None),
])
def test_code_normaliser_is_conservative(cell, code, desc):
    row = ce.normalize_wc_class_row({"code": cell, "description": ""})
    assert row["code"] == code
    assert (row["description"] or None) == desc


def test_a_stated_description_is_never_overwritten_by_the_split():
    row = ce.normalize_wc_class_row({"code": "8810 Clerical", "description": "Office staff"})
    assert row["code"] == "8810"
    assert row["description"] == "Office staff"


# ── 8.1 state, from the rows, positive evidence only ─────────────────────────

def test_single_state_labels_the_rating_sheet_and_part_one(schema130):
    facts = {"wc_class_codes": _rows()}
    mapped, gaps, blanks = _gaps(schema130, facts)
    assert mapped["WorkersCompensation_RateState_StateOrProvinceName_A"] == "CO"
    assert mapped["WorkersCompensation_PartOne_StateOrProvinceCode_A"] == "CO"
    # Three CO rows are ONE state: B and C are owned blanks, not "CO, CO".
    assert "WorkersCompensation_PartOne_StateOrProvinceCode_B" in blanks
    assert "WorkersCompensation_PartOne_StateOrProvinceCode_B" not in gaps
    assert not mapped.get("WorkersCompensation_PartOne_StateOrProvinceCode_B")


def test_two_states_list_both_in_part_one_and_leave_the_sheet_blank(schema130):
    rows = _rows()
    rows[2]["state"] = "TX"
    facts = {"wc_class_codes": rows}
    mapped, gaps, blanks = _gaps(schema130, facts)
    assert mapped["WorkersCompensation_PartOne_StateOrProvinceCode_A"] == "CO"
    assert mapped["WorkersCompensation_PartOne_StateOrProvinceCode_B"] == "TX"
    # Our template prints ONE rating sheet; two states cannot share it. Blank,
    # owned, never the LLM's guess.
    assert "WorkersCompensation_RateState_StateOrProvinceName_A" in blanks
    assert "WorkersCompensation_RateState_StateOrProvinceName_A" not in gaps


def test_rows_without_a_state_print_no_state(schema130):
    rows = [dict(r, state=None) for r in _rows()]
    mapped, gaps, blanks = _gaps(schema130, {"wc_class_codes": rows})
    assert not mapped.get("WorkersCompensation_RateState_StateOrProvinceName_A")
    assert not mapped.get("WorkersCompensation_PartOne_StateOrProvinceCode_A")
    assert "WorkersCompensation_PartOne_StateOrProvinceCode_A" not in gaps


def test_state_helpers_ignore_junk():
    rows = [{"state": "Colorado"}, {"state": "co"}, {"state": ""}, "not a row", {"state": "TX"}]
    assert ce.wc_class_row_states(rows) == ["CO", "TX"]
    assert ce.wc_class_shared_state(rows) is None
    assert ce.wc_class_shared_state([{"state": "co"}, {"state": "CO"}]) == "CO"
    assert ce.wc_class_shared_state([]) is None
    assert ce.wc_class_shared_state("nope") is None


# ── 8.2 payroll by state, DERIVED from a complete table (D28) ────────────────

def test_complete_table_derives_payroll_by_state_with_provenance():
    from services.extraction_service import derive_wc_facts_from_class_rows
    facts = {"wc_class_codes": _rows()}
    assert derive_wc_facts_from_class_rows(facts) is True
    env = facts["wc_payroll_by_state"]
    assert env["value"] == {"CO": "$800,000"}
    assert env["evidence_state"] == "derived"
    assert env["derivation"]["inputs"] == ["wc_class_codes"]


def test_two_states_sum_per_state():
    rows = _rows()
    rows[2]["state"] = "TX"
    assert ce.wc_payroll_by_state_from_rows(rows) == {"CO": "$280,000", "TX": "$520,000"}


def test_partial_table_derives_nothing():
    """A state total built from half the rows is a WRONG value (H1-F class)."""
    rows = _rows()
    rows[1]["state"] = None
    assert ce.wc_payroll_by_state_from_rows(rows) is None
    rows = _rows()
    rows[0]["payroll"] = ""
    assert ce.wc_payroll_by_state_from_rows(rows) is None
    assert ce.wc_payroll_by_state_from_rows([]) is None
    assert ce.wc_payroll_by_state_from_rows([{"code": "", "state": "", "payroll": ""}]) is None


def test_a_stated_by_state_value_is_never_overwritten():
    from services.extraction_service import derive_wc_facts_from_class_rows
    facts = {"wc_class_codes": _rows(), "wc_payroll_by_state": {"CO": "$1"}}
    derive_wc_facts_from_class_rows(facts)
    assert facts["wc_payroll_by_state"] == {"CO": "$1"}
    facts = {"wc_class_codes": _rows(),
             "wc_payroll_by_state": {"value": {"CO": "$1"}, "source": "producer"}}
    derive_wc_facts_from_class_rows(facts)
    assert facts["wc_payroll_by_state"]["value"] == {"CO": "$1"}


def test_our_own_derivation_follows_the_edited_table():
    """An edited table must never leave a stale derivation behind."""
    from services.extraction_service import derive_wc_facts_from_class_rows
    facts = {"wc_class_codes": _rows()}
    derive_wc_facts_from_class_rows(facts)
    facts["wc_class_codes"][2]["state"] = "TX"
    derive_wc_facts_from_class_rows(facts)
    assert facts["wc_payroll_by_state"]["value"] == {"CO": "$280,000", "TX": "$520,000"}
    facts["wc_class_codes"][2]["state"] = ""            # table no longer complete
    derive_wc_facts_from_class_rows(facts)
    assert not facts["wc_payroll_by_state"]


def test_the_merge_re_derives_the_multi_state_flag_from_the_derived_dict():
    """`merge_facts` reads the by-state keys to set `wc_multi_state`; the
    derived envelope must be unwrapped there or the flag stays False."""
    import inspect
    from services import extraction_service as es
    src = inspect.getsource(es.merge_facts)
    idx_derive = src.index("derive_wc_facts_from_class_rows(mf)")
    idx_flag = src.index("_MONOPOLISTIC_STATES = ")
    assert idx_derive < idx_flag, "derive BEFORE the flag re-derivation"
    assert 'wc_by_state.get("value")' in src


# ── 8.2 officers: names, state, included / excluded ──────────────────────────

@pytest.mark.parametrize("row,code", [
    ({"include": True, "exclude": False}, "INC"),
    ({"include": False, "exclude": True}, "EXC"),
    ({"include": True, "exclude": True}, None),           # contradiction -> blank
    ({"include": False, "exclude": False}, None),         # silence -> blank
    ({"include_exclude": "Included"}, "INC"),
    ({"include_exclude": "excluded"}, "EXC"),
    ({"include_exclude": "EXC"}, "EXC"),
    ({"treatment": "inc"}, "INC"),
    ({"include_exclude": "maybe"}, None),                 # unrecognised -> blank
    ({"include_exclude": "included and excluded"}, None),
    ("Jane Doe", None),
])
def test_officer_treatment_code(row, code):
    assert ce.officer_treatment_code(row) == code


def test_officer_rows_stamp_state_and_treatment(schema130):
    facts = {"wc_officers": [
        {"name": "Jane Doe", "title": "President", "ownership_pct": "100",
         "include": True, "exclude": False, "state": "CO"},
        {"name": "Bob Roe", "title": "VP", "include_exclude": "Excluded"},
        {"name": "Ann Poe"},
    ]}
    mapped, gaps, blanks = _gaps(schema130, facts)
    assert mapped["WorkersCompensation_Individual_FullName_A"] == "Jane Doe"
    assert mapped["WorkersCompensation_Individual_IncludedExcludedCode_A"] == "INC"
    assert mapped["WorkersCompensation_Individual_StateOrProvinceCode_A"] == "CO"
    assert mapped["WorkersCompensation_Individual_IncludedExcludedCode_B"] == "EXC"
    # Ann's treatment is unknown: owned blank, never an LLM guess.
    assert "WorkersCompensation_Individual_IncludedExcludedCode_C" in blanks
    assert "WorkersCompensation_Individual_IncludedExcludedCode_C" not in gaps
    assert not mapped.get("WorkersCompensation_Individual_IncludedExcludedCode_C")


def test_officer_table_shows_treatment_as_a_word():
    facts = {"wc_officers": [{"name": "Jane", "include": True, "exclude": False},
                             {"name": "Bob", "include_exclude": "Excluded"},
                             {"name": "Ann"}]}
    rows = sc.rows_from_facts("wc_officers", facts)
    assert [r["include_exclude"] for r in rows] == ["Included", "Excluded", ""]


def test_six_four_officer_check_reads_the_typed_word():
    """A producer typing "Excluded" into the table settles the 6.4 item."""
    flags = {"has_workers_comp": True}
    assert ce.wc_officer_treatment_status(
        {"wc_officers": [{"name": "A", "include_exclude": "Excluded"}]}, flags) == ce.STATUS_SATISFIED
    assert ce.wc_officer_treatment_status(
        {"wc_officers": [{"name": "A", "include_exclude": "maybe"}]}, flags) == ce.STATUS_MISSING
    # H1 pins, unchanged
    assert ce.wc_officer_treatment_status(
        {"wc_officers": [{"name": "A", "include": True}]}, flags) == ce.STATUS_SATISFIED
    assert ce.wc_officer_treatment_status(
        {"wc_officers": [{"name": "A"}]}, flags) == ce.STATUS_MISSING


# ── 8.3 the classification boundary ──────────────────────────────────────────

def test_no_class_code_box_reaches_the_llm_when_no_table_was_extracted(schema130):
    """Right-or-blank on every WC code box: the LLM is never asked for a
    class code it could only produce from prose."""
    for facts in ({"operations_description": "Residential roofing", "wc_class_codes": [],
                   "wc_officers": []},
                  {"operations_description": "Residential roofing"}):
        mapped, gaps, blanks = _gaps(schema130, facts)
        leaked = [k for k in gaps if "ClassificationCode" in k or "RateClass_DescriptionCode" in k]
        assert not leaked, leaked


def test_the_officer_class_code_prints_only_what_a_row_carries(schema130):
    facts = {"wc_officers": [{"name": "Jane", "class_code": "8810"}, {"name": "Bob"}]}
    mapped, gaps, blanks = _gaps(schema130, facts)
    assert mapped["WorkersCompensation_Individual_RatingClassificationCode_A"] == "8810"
    assert "WorkersCompensation_Individual_RatingClassificationCode_B" in blanks
    assert "WorkersCompensation_Individual_RatingClassificationCode_B" not in gaps


def test_nothing_in_the_repo_generates_a_wc_class_code():
    """8.3: extract, retain, normalize, compare - never recommend. The only
    suggester is NAICS/SIC; the class-code vote only compares."""
    import inspect
    from services import naics_suggester, sqs_service
    src = inspect.getsource(naics_suggester).lower()
    assert "wc_class" not in src and "ncci" not in src
    vote = inspect.getsource(sqs_service._codes_to_industry)
    assert "return None" in vote and "recommend" not in vote.lower()


def test_class_code_vote_ignores_the_new_count_columns():
    """The vote reads NAMED keys only; a payroll of 540300 or a count of 5403
    must never become class 5403 (H1-F / H1-H)."""
    from services.sqs_service import _class_code_tokens
    rows = [{"code": "2003", "payroll": "$540,300", "full_time_employees": "5403",
             "description": "2026 remodel"}]
    assert _class_code_tokens(rows) == {"2003"}


def test_count_columns_are_never_read_as_money():
    from services.extraction_service import _CLASS_EXPOSURE_COLUMNS
    cols = _CLASS_EXPOSURE_COLUMNS.get("wc_class_codes", ())
    assert "payroll" in cols
    assert "full_time_employees" not in cols and "part_time_employees" not in cols


# ── extraction: the row schema and the chunk-union identity ──────────────────

def test_extraction_schema_carries_the_counts_and_moved_to_v17():
    from services import extraction_service as es
    assert es.PROMPT_VERSION == "v17" and es.SCHEMA_VERSION == "v17"
    assert '"full_time_employees": string or null' in es._EXTRACT_SCHEMA
    assert '"part_time_employees": string or null' in es._EXTRACT_SCHEMA


def test_the_same_row_printed_in_TWO_SHAPES_folds():
    """THE LIVE DRY-RUN DEFECT (2026-08-27). A premium summary prints one
    combined cell ("8810 Clerical"); the rating sheet prints the code and the
    wording in separate columns. That is ONE row printed twice, and the union
    must fold it - the identity used to be computed on the raw cell, before
    normalisation, so the two shapes never matched, both rows survived, and the
    payroll-by-state derived from them DOUBLED.
    """
    from services.extraction_service import derive_wc_facts_from_class_rows, _dedupe_schedule_rows
    printed_twice = [
        {"code": "8810 Clerical", "state": "CO", "payroll": "$100,000"},
        {"code": "5551 Roofing", "state": "CO", "payroll": "$520,000"},
        {"code": "8810", "description": "Clerical - office and administrative",
         "state": "CO", "payroll": "$100,000", "full_time_employees": "2"},
        {"code": "5551", "description": "Roofing installation", "state": "CO",
         "payroll": "$520,000", "full_time_employees": "8"},
    ]
    folded = _dedupe_schedule_rows("wc_class_codes", printed_twice)
    assert len(folded) == 2, folded
    # and the later printing's columns fill the summary row's gaps
    assert folded[0]["full_time_employees"] == "2"
    assert folded[0]["description"] == "Clerical - office and administrative"
    facts = {"wc_class_codes": folded}
    derive_wc_facts_from_class_rows(facts)
    assert facts["wc_payroll_by_state"]["value"] == {"CO": "$620,000"}   # not $1,240,000


def test_the_code_token_has_one_reader():
    """The normaliser and the union identity must read a code the SAME way."""
    assert ce.wc_class_code_token({"code": "8810 Clerical"}) == "8810"
    assert ce.wc_class_code_token({"code": "5551 - Roofing"}) == "5551"
    assert ce.wc_class_code_token("8810A") == "8810A"
    assert ce.wc_class_code_token({"code": "Roofing"}) == ""
    assert ce.wc_class_code_token({}) == ""
    assert ce.wc_class_code_token(None) == ""


def test_the_same_rating_row_printed_twice_folds_but_two_locations_do_not():
    from services.extraction_service import _dedupe_schedule_rows
    twice = [{"code": "5551", "state": "CO", "payroll": "$520,000"},
             {"code": "5551", "state": "CO", "payroll": "$520,000", "full_time_employees": "8"}]
    merged = _dedupe_schedule_rows("wc_class_codes", twice)
    assert len(merged) == 1 and merged[0]["full_time_employees"] == "8"
    two_locations = [{"code": "5551", "state": "CO", "payroll": "$520,000"},
                     {"code": "5551", "state": "CO", "payroll": "$90,000"}]
    assert len(_dedupe_schedule_rows("wc_class_codes", two_locations)) == 2
    no_identity = [{"code": "5551", "state": "CO"}, {"code": "5551", "state": "CO"}]
    assert len(_dedupe_schedule_rows("wc_class_codes", no_identity)) == 2


# ── questionnaire routing ─────────────────────────────────────────────────────

def test_the_client_table_is_not_flagged_producer_review_for_its_hidden_column():
    """`wc_class_codes` IS an insurance-judgment fact; the TABLE is the
    client's exposure answer with that column stripped. The eligibility door
    must leave the table alone."""
    from services.question_eligibility import overlay_for
    q = {"field_name": "schedule::wc_class_codes", "field_type": "schedule",
         "_canonical_key": "wc_class_codes", "audience": "client"}
    assert overlay_for(q, {"wc_class_codes": {"value": [], "source": "ai"}}) == {}
    # and the SCALAR question still routes to the producer (C4 pin, untouched)
    scalar = {"field_name": "wc_class_codes", "_canonical_key": "wc_class_codes",
              "audience": "client"}
    assert overlay_for(scalar, {}).get("audience") == "producer"


def test_schedule_taxonomy_routes_the_officers_table_to_the_agency():
    from services.arq_service import _finalize_schedule_taxonomy
    qs = [{"field_type": "schedule", "schedule_key": "wc_officers"},
          {"field_type": "schedule", "schedule_key": "wc_class_codes"},
          {"field_type": "schedule", "schedule_key": "auto_vin_schedule"},
          {"field_type": "text", "audience": "producer"}]
    _finalize_schedule_taxonomy(qs)
    assert qs[0]["audience"] == "producer" and qs[0]["bucket"] == "agency"
    assert qs[1]["audience"] == "client" and qs[1]["bucket"] == "client"
    assert qs[2]["audience"] == "client"                      # the four originals unchanged
    assert qs[3]["audience"] == "producer"                    # non-schedules untouched
    for q in qs[:3]:
        assert q["suppressed"] is False


def test_schedule_questions_carry_the_producer_only_flag_and_capacity():
    from services.arq_service import _build_schedule_questions
    qs = _build_schedule_questions({"wc_officers": {"ACORD_130"}, "wc_class_codes": {"ACORD_130"}},
                                   {"wc_class_codes": _rows()})
    by = {q["schedule_key"]: q for q in qs}
    assert by["wc_officers"]["producer_only"] is True and by["wc_officers"]["row_capacity"] == 4
    assert by["wc_class_codes"]["producer_only"] is False
    assert len(by["wc_class_codes"]["current_rows"]) == 3
    assert by["wc_class_codes"]["current_rows"][0]["full_time_employees"] == "2"


def test_the_scalar_wc_questions_are_dropped_when_their_tables_exist():
    from services.arq_service import _drop_scalar_duplicates_of_schedule_questions
    qs = [{"field_type": "schedule", "_canonical_key": "wc_class_codes"},
          {"field_type": "schedule", "_canonical_key": "wc_officers"},
          {"field_type": "text", "field_name": "wc_class_codes", "_canonical_key": "wc_class_codes"},
          {"field_type": "text", "field_name": "wc_officers", "_canonical_key": "wc_officers"},
          {"field_type": "text", "field_name": "wc_xmod", "_canonical_key": "wc_xmod"}]
    dropped = _drop_scalar_duplicates_of_schedule_questions(qs)
    assert dropped == 2
    assert [q.get("field_name") for q in qs if q["field_type"] == "text"] == ["wc_xmod"]


def test_the_130_rating_fields_collapse_into_one_table_question():
    from services.arq_service import _partition_schedule_fields
    missing = {
        "WorkersCompensation_RateClass_ClassificationCode_A": {"ACORD_130"},
        "WorkersCompensation_RateClass_FullTimeEmployeeCount_B": {"ACORD_130"},
        "WorkersCompensation_Individual_IncludedExcludedCode_A": {"ACORD_130"},
        "Producer_FullName_A": {"ACORD_130"},
    }
    values = {k: "" for k in missing}
    out = _partition_schedule_fields(missing, values)
    assert out == {"wc_class_codes": {"ACORD_130"}, "wc_officers": {"ACORD_130"}}
    assert list(missing) == ["Producer_FullName_A"]


def test_multi_state_hard_stop_resolves_by_opening_the_table():
    from services.issue_registry import resolution_for
    res = resolution_for("wc_multi_state_no_breakdown")
    assert res and res.get("mode") == "schedule" and res.get("schedule_key") == "wc_class_codes"


# ── cross-form: the state-total check reads the shape the merge writes ───────

def test_multi_state_total_check_runs_on_the_dict_shape():
    from services.cross_form_validator import _check_wc_multi_state_payroll_breakdown
    flags = {"wc_multi_state": True}
    ok = _check_wc_multi_state_payroll_breakdown(
        {"wc_payroll_by_state": {"CO": "$280,000", "TX": "$520,000"}, "total_payroll": "$800,000"},
        flags, {"ACORD_130"})
    assert ok == []
    off = _check_wc_multi_state_payroll_breakdown(
        {"wc_payroll_by_state": {"CO": "$280,000", "TX": "$520,000"}, "total_payroll": "$1,200,000"},
        flags, {"ACORD_130"})
    assert [i["code"] for i in off] == ["wc_state_payroll_total_mismatch"]
    assert off[0]["type"] == "hard_stop"
    derived = _check_wc_multi_state_payroll_breakdown(
        {"wc_payroll_by_state": {"value": {"CO": "$800,000"}, "source": "derived"},
         "total_payroll": "$800,000"}, flags, {"ACORD_130"})
    assert derived == []
    free_text = _check_wc_multi_state_payroll_breakdown(
        {"wc_payroll_by_state": "CO 280k, TX 520k", "total_payroll": "$1"}, flags, {"ACORD_130"})
    assert free_text == []                                    # a string has no total


# ── the payroll period follows H1's own rule once the table is filled ────────

def test_a_typed_annual_payroll_column_satisfies_the_period_check():
    flags = {"has_workers_comp": True}
    facts = {"wc_payroll": "$800,000", "wc_class_codes": _rows()}
    assert ce.wc_payroll_period_status(facts, flags) == ce.STATUS_SATISFIED
    assert ce.wc_payroll_period_status({"wc_payroll": "$800,000"}, flags) == ce.STATUS_MISSING


# ── H3-D: the three defects the first live run found, pinned ─────────────────

def test_no_schedule_question_is_hidden_as_machine_worded():
    """THE LIVE DEFECT (2026-08-27). Both WC tables were built, routed to
    Client / Agency, and then suppressed by `_hide_machine_worded_questions`
    because `question_text`'s default template began "Please provide your " -
    which is that filter's marker for a question nobody worded properly.

    TWO conditions, deliberately: the wording must be right AND a table must be
    structurally exempt. The four original schedules only ever escaped by the
    accident of each having a hand-written override.
    """
    from services.arq_service import _MACHINE_QUESTION_PREFIX, _hide_machine_worded_questions
    for list_key in sc.SCHEDULE_DEFS:
        text = sc.question_text(list_key)
        assert text and not text.startswith(_MACHINE_QUESTION_PREFIX), (
            f"{list_key}'s question starts with the machine-worded prefix: {text!r}")
    # ...and even if one did, a table is exempt by construction.
    qs = [{"field_type": "schedule", "schedule_key": "wc_class_codes",
           "question": _MACHINE_QUESTION_PREFIX + "employee groups.", "audience": "client"},
          {"field_type": "text", "question": _MACHINE_QUESTION_PREFIX + "kah code.",
           "audience": "client"}]
    assert _hide_machine_worded_questions(qs) == 1          # only the text one moves
    assert qs[0]["audience"] == "client"
    assert qs[1]["audience"] == "internal"


def test_no_client_question_asks_for_a_classification_code():
    """Core principle 5 / client 8.3, swept across the WHOLE question map.

    `narrative_target_markets` (C4-S) and `narrative_growth_trends` (H3-D) were
    both narrative slots repurposed into classification questions, found one at
    a time, a month apart. This sweep is so a third cannot ship: any question
    naming a classification system must be producer-routed.
    """
    from services.arq_service import _FIELD_QUESTION_MAP, _FIELD_HINT_MAP
    from services.question_eligibility import (
        INSURANCE_JUDGMENT_FACTS, INSURANCE_JUDGMENT_QUESTION_KEYS,
    )
    vocab = ("class code", "classification code", "naics", "sic code",
             "emod", "xmod", "experience modifier", "ncci")
    # NAMING a classification is allowed when the copy explicitly says the
    # client does NOT supply it - that IS principle 5 being honoured, and
    # `gl_class_codes` does exactly this ("your agent will assign the
    # classification code"). The structural second condition, so a necessary
    # test does not become a wrong one.
    disclaimed = ("your agent will", "your agent assigns", "we will assign",
                  "your agent or underwriter", "if unsure, leave blank")
    producer_owned = set(INSURANCE_JUDGMENT_FACTS) | set(INSURANCE_JUDGMENT_QUESTION_KEYS)
    offenders = []
    for key, text in list(_FIELD_QUESTION_MAP.items()) + list(_FIELD_HINT_MAP.items()):
        if key in producer_owned:
            continue
        low = str(text).lower()
        if any(v in low for v in vocab) and not any(d in low for d in disclaimed):
            offenders.append(f"{key}: {str(text)[:70]}")
    assert not offenders, (
        "client-eligible question(s) asking for an insurance classification: "
        + "; ".join(sorted(offenders)))


def test_nothing_inside_a_wc_schedule_row_reaches_the_llm(schema130):
    """Right-or-blank across the WHOLE family (D45 generalised).

    Live: the officer rows' unbound columns were filled from the employee-group
    table - W2 printed three officers on a package with none, carrying the three
    group payrolls; W1 grew an officer whose duties were "Roofing installation".
    """
    facts = {"wc_class_codes": _rows(),
             "wc_officers": [{"name": "Dana", "title": "President", "include": True}]}
    for f in (facts, {"wc_payroll": "$640,000", "naics_code": "238160"}):
        _m, gaps, _b = _gaps(schema130, f)
        leaked = [k for k in gaps if re.search(
            r"Individual_|RateClass_|PartThree_|StateCoverage_\w+_ModificationFactor", k)]
        assert not leaked, leaked


def test_officer_rows_beyond_the_list_carry_nothing(schema130):
    """The phantom officer row, pinned by its live shape."""
    facts = {"wc_class_codes": _rows(),          # 3 groups
             "wc_officers": [{"name": "Dana Whitfield", "include": True}]}   # 1 officer
    mapped, gaps, blanks = _gaps(schema130, facts)
    for row in "BCD":
        for col in ("RemunerationAmount", "DutiesDescription", "BirthDate", "FullName"):
            f = f"WorkersCompensation_Individual_{col}_{row}"
            assert not mapped.get(f), f"{f} = {mapped.get(f)!r}"
            assert f not in gaps, f


def test_part_three_other_states_is_always_blank(schema130):
    """Part 3 means states NOT in Part 1; live it printed the same states."""
    mapped, gaps, blanks = _gaps(schema130, {"wc_class_codes": _rows()})
    assert mapped["WorkersCompensation_PartOne_StateOrProvinceCode_A"] == "CO"
    for row in "ABC":
        f = f"WorkersCompensation_PartThree_StateOrProvinceCode_{row}"
        assert not mapped.get(f) and f not in gaps


def test_only_the_experience_mod_fills_a_rating_factor(schema130):
    """Live: INCREASED LIMITS carried the $1,000,000 EL limit as a multiplier,
    and ASSIGNED RISK SURCHARGE carried the experience mod."""
    mapped, gaps, _b = _gaps(schema130, {"wc_xmod": "0.92", "wc_el_each_accident": "$1,000,000",
                                         "wc_class_codes": _rows()})
    assert mapped["WorkersCompensationStateCoverage_ExperienceOrMerit_ModificationFactor_A"] == "0.92"
    for other in ("IncreasedLimits", "AssignedRiskSurcharge", "Deductible", "ScheduleRating"):
        f = f"WorkersCompensationStateCoverage_{other}_ModificationFactor_A"
        assert not mapped.get(f) and f not in gaps, f
    # no mod stated -> the box is blank, never a borrowed number
    m2, g2, _ = _gaps(schema130, {"wc_el_each_accident": "$1,000,000"})
    f = "WorkersCompensationStateCoverage_ExperienceOrMerit_ModificationFactor_A"
    assert not m2.get(f) and f not in g2


def test_the_premium_block_state_agrees_with_the_rating_sheet(schema130):
    """Live W2: the sheet correctly refused to name a state and the premium
    block below it printed CO anyway."""
    one = _gaps(schema130, {"wc_class_codes": _rows()})[0]
    assert one["WorkersCompensation_RateState_StateOrProvinceName_A1"] == "CO"
    two_rows = _rows(); two_rows[2]["state"] = "TX"
    two = _gaps(schema130, {"wc_class_codes": two_rows})[0]
    assert not two.get("WorkersCompensation_RateState_StateOrProvinceName_A")
    assert not two.get("WorkersCompensation_RateState_StateOrProvinceName_A1")


def test_a_mod_effective_date_is_not_a_policy_effective_date():
    """Live: every WC package printing a mod effective date raised a false
    "Policy Effective Date - values differ" card and capped SQS at 85."""
    from services.underwriting_consistency import _text_scan_values
    assert _text_scan_values("Experience Modification Effective Date: 07/13/2026",
                             "effective_date") == []
    assert _text_scan_values("Anniversary Rating Date: 07/13/2026", "effective_date") == []
    # the real thing still scans - both spellings
    assert _text_scan_values("Policy Effective Date: 09/17/2026", "effective_date") == ["09/17/2026"]
    assert _text_scan_values("Effective Date: 01/02/2027", "effective_date") == ["01/02/2027"]
    # and a mod mentioned a line earlier never suppresses a real one
    assert _text_scan_values("Experience Modification: 0.92\nPolicy Effective Date: 09/17/2026",
                             "effective_date") == ["09/17/2026"]
