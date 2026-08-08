"""Covered-auto symbol table, reasoning, stamping and validation.

Context (2026-08-07): a client reported two warnings on a submission where
nothing was wrong - "Hired/Non-Owned auto exposure detected but coverage
symbol(s) not defined" and "Physical damage coverage requested but symbols
undefined" - on a policy whose declarations plainly show Symbol 01 for Auto
Liability and Symbol 07 for Comprehensive and Collision.

Two defects, both fixed and both guarded here:
  1. The checks read five fact keys nothing has ever written, so they fired on
     EVERY auto submission regardless of the document.
  2. They demanded Symbols 8 and 9 specifically, when Symbol 1 (any auto) is
     broader and already designates hired and non-owned autos.

`test_client_reported_case_is_silent` is the replay of the client's literal
values and is the test that must never be allowed to fail.
"""

import json
import os
import re

import pytest

from services import auto_symbols as sym
from services.cross_form_validator import (
    _check_auto_hired_nonowned_symbols,
    _check_auto_owned_fleet_symbol_gap,
    _check_auto_symbol_to_exposure_alignment,
    _check_auto_symbols_captured,
)

SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "forms_schemas"
)

_ALL_FORMS = {"ACORD_127", "ACORD_137_CA", "ACORD_137_CO", "ACORD_138_CA",
              "ACORD_138_CO", "ACORD_160", "ACORD_25", "ACORD_131"}


def _schema(form_id):
    with open(os.path.join(SCHEMA_DIR, f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


# ── The table cannot drift from ACORD ─────────────────────────────────────────

def _live_symbol_tooltips():
    """{symbol field base name: tooltip} across every real schema.

    ACORD stacks one symbol grid PER COVERAGE LINE (rows A, B, C, E-H), and each
    row offers only the symbols legal for that coverage - so a given symbol may
    exist on row C and not row A. Bindings are therefore checked by BASE name
    across all rows, not at a fixed row.
    """
    out = {}
    for form in _ALL_FORMS:
        for name, meta in _schema(form).items():
            if "Symbol_" in name and "Indicator" in name:
                out.setdefault(name.rsplit("_", 1)[0], meta.get("tu") or "")
    return out


def test_every_symbol_binds_to_a_live_acord_field():
    """Each row's ACORD field must exist on a real schema.

    This is what makes the table trustworthy: the definitions are ACORD's, not
    ours, and if ACORD's field names ever change the build fails rather than the
    stamper silently writing to nothing.
    """
    live = _live_symbol_tooltips()
    unbound = [
        (n, s.family, sym.FAMILY_FIELD_PREFIX[s.family] + s.word + "Indicator")
        for n, s in sym.BY_NUMBER.items()
        if sym.FAMILY_FIELD_PREFIX[s.family] + s.word + "Indicator" not in live
    ]
    assert not unbound, f"symbols with no live ACORD field: {unbound}"


def test_every_symbol_description_matches_acord_tooltip():
    """Our plain-English description must be ACORD's own wording."""
    live = _live_symbol_tooltips()

    mismatched = []
    for number, s in sym.BY_NUMBER.items():
        base = sym.FAMILY_FIELD_PREFIX[s.family] + s.word + "Indicator"
        tu = live.get(base, "").lower()
        tu = tu.replace("check the box (if applicable): indicates ", "")
        tu = re.sub(r"^that\s+", "", tu)
        tu = re.sub(r"\s+", " ", tu).strip().rstrip(".")
        ours = re.sub(r"\s+", " ", s.description.lower()).strip()
        # ACORD appends usage notes after the definition on some rows; ours must
        # be the leading definition.
        if not tu.startswith(ours):
            mismatched.append((number, ours, tu[:90]))
    assert not mismatched, f"description drifted from ACORD tooltip: {mismatched}"


def test_only_the_liability_row_of_the_symbol_grid_is_stamped():
    """Row A is the only grid row identifiable from the schema.

    Row A is the only one offering symbol 1 (any auto) and symbol 9 (non-owned),
    both liability-only designations. Rows E-H offer identical symbol sets and
    cannot be told apart, so stamping them would be a guess that writes a wrong
    value onto a form.
    """
    d = json.load(open(os.path.join(SCHEMA_DIR, "ACORD_137_CA_schema.json"),
                       encoding="utf-8"))
    rows_with_one = {
        k.rsplit("_", 1)[1] for k in d
        if k.startswith("Vehicle_BusinessAutoSymbol_OneIndicator_")
    }
    assert rows_with_one == {"A"}


def test_families_use_disjoint_number_ranges():
    """Family detection reads the bare number, so the sets must not overlap."""
    seen = {}
    for s in sym.BY_NUMBER.values():
        assert seen.setdefault(s.number, s.family) == s.family
    assert len(sym.BY_NUMBER) == 37


def test_iso_symbols_absent_from_the_acord_grid_are_not_invented():
    """5 and 19 are real ISO symbols that ACORD does NOT print on the grid.

    They belong in the "Other symbol" box. Inventing rows for them here would
    make the stamper tick a checkbox that does not exist.
    """
    assert 5 not in sym.BY_NUMBER
    assert 19 not in sym.BY_NUMBER
    assert sym.unrecognised([1, 5, 19]) == [5, 19]


# ── Parsing every shape this fact arrives in ──────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    # Current extraction shape
    ([{"coverage": "liability", "symbols": [1]},
      {"coverage": "comprehensive", "symbols": [7]},
      {"coverage": "collision", "symbols": [7]}],
     {"liability": [1], "comprehensive": [7], "collision": [7]}),
    # Legacy bare list (pre-2026-08 sessions must keep working)
    ([1, 7], {"unspecified": [1, 7]}),
    # Producer free text typed into the resolution modal
    ("Liability 1, Comprehensive 7, Collision 7",
     {"liability": [1], "comprehensive": [7], "collision": [7]}),
    # Dict
    ({"liability": [1], "comp": ["07"]}, {"liability": [1], "comprehensive": [7]}),
    # Leading zeros exactly as printed on a dec page
    ([{"coverage": "Auto Liability", "symbols": ["01"]}], {"liability": [1]}),
    (None, {}),
    ([], {}),
])
def test_parse_symbols_shapes(raw, expected):
    assert sym.parse_symbols(raw) == expected


def test_parse_symbols_unwraps_annotated_envelope():
    assert sym.parse_symbols({"value": [1, 7], "ocr_confident": True}) == {
        "unspecified": [1, 7]
    }


# ── Subsumption: the client's actual underwriting point ───────────────────────

def test_symbol_1_covers_hired_and_non_owned():
    assert sym.covers([1], sym.HIRED) is True
    assert sym.covers([1], sym.NONOWNED) is True
    assert sym.covers([1], sym.OWNED) is True


def test_symbol_8_and_9_cover_only_their_own_exposure():
    assert sym.covers([8], sym.HIRED) is True
    assert sym.covers([8], sym.NONOWNED) is False
    assert sym.covers([8, 9], sym.NONOWNED) is True
    assert sym.covers([8, 9], sym.OWNED) is False


def test_symbol_7_is_the_scheduled_fleet():
    assert sym.covers([7], sym.SCHEDULED) is True
    assert sym.covers([7], sym.HIRED) is False


def test_covers_declines_on_unknown_or_unrecognised():
    """None means 'cannot say' and must never be read as a coverage gap."""
    assert sym.covers([], sym.HIRED) is None
    assert sym.covers([19], sym.HIRED) is None
    assert sym.covers([1, 19], sym.HIRED) is None


@pytest.mark.parametrize("numbers,family", [
    ([1, 7], sym.BUSINESS_AUTO),
    ([41, 47], sym.TRUCKERS),
    ([61, 67], sym.MOTOR_CARRIER),
    ([21, 30], sym.GARAGE),
    ([1, 41], None),        # spans two families - cannot say
    ([19], None),
])
def test_detect_family(numbers, family):
    assert sym.detect_family(numbers) == family


def test_family_falls_back_to_flags_only_when_nothing_captured():
    assert sym.family_for({}, {"has_truckers_coverage": True}) == sym.TRUCKERS
    # A captured business-auto symbol beats the trucking flag - the number is
    # evidence, the flag is an inference.
    facts = {"auto_covered_symbols": [1]}
    assert sym.family_for(facts, {"has_truckers_coverage": True}) == sym.BUSINESS_AUTO


# ── The client's reported case ────────────────────────────────────────────────

CLIENT_FACTS = {
    "auto_covered_symbols": [
        {"coverage": "liability", "symbols": [1]},
        {"coverage": "comprehensive", "symbols": [7]},
        {"coverage": "collision", "symbols": [7]},
    ],
    "auto_vin_schedule": [{"year": "2021", "make": "Ford", "model": "F-150"}],
}
CLIENT_FLAGS = {
    "has_auto_coverage": True,
    "auto_has_hired_nonowned": True,
    "auto_has_physical_damage": True,
}


def test_client_reported_case_is_silent():
    """Symbol 1 liability + Symbol 7 comp/collision: zero issues.

    This is the exact submission the client raised. Both warnings in the
    screenshot must be gone, and no new one may take their place.
    """
    triggered = {"ACORD_127"}
    issues = []
    for check in (_check_auto_hired_nonowned_symbols,
                  _check_auto_symbols_captured,
                  _check_auto_owned_fleet_symbol_gap,
                  _check_auto_symbol_to_exposure_alignment):
        issues += check(CLIENT_FACTS, CLIENT_FLAGS, triggered)
    assert issues == [], [i["message"] for i in issues]


def test_hired_nonowned_warning_still_fires_on_a_real_gap():
    """Symbol 2 (owned only) genuinely does not reach hired or non-owned."""
    facts = {"auto_covered_symbols": [{"coverage": "liability", "symbols": [2]}]}
    issues = _check_auto_hired_nonowned_symbols(facts, CLIENT_FLAGS, {"ACORD_127"})
    assert len(issues) == 1
    msg = issues[0]["message"]
    assert "hired" in msg and "non-owned" in msg
    assert "owned autos only are covered" in msg   # names what the policy says


def test_hired_nonowned_silent_when_symbol_8_and_9_present():
    facts = {"auto_covered_symbols": [{"coverage": "liability", "symbols": [8, 9]}]}
    assert _check_auto_hired_nonowned_symbols(facts, CLIENT_FLAGS, {"ACORD_127"}) == []


def test_no_symbols_produces_exactly_one_transfer_advisory():
    """Not three complaints - one, and worded as a transfer."""
    facts = {"auto_vin_schedule": [{"year": "2021"}]}
    triggered = {"ACORD_127"}
    issues = []
    for check in (_check_auto_hired_nonowned_symbols,
                  _check_auto_symbols_captured,
                  _check_auto_owned_fleet_symbol_gap,
                  _check_auto_symbol_to_exposure_alignment):
        issues += check(facts, CLIENT_FLAGS, triggered)
    assert len(issues) == 1
    assert issues[0]["code"] == "auto_symbols_not_captured"
    assert "declarations designate covered autos by symbol" in issues[0]["message"]


def test_physical_damage_warning_fires_when_only_liability_is_designated():
    facts = {"auto_covered_symbols": [
        {"coverage": "liability", "symbols": [1]},
        {"coverage": "medical", "symbols": [2]},
    ]}
    issues = _check_auto_symbol_to_exposure_alignment(facts, CLIENT_FLAGS, {"ACORD_127"})
    codes = [i["code"] for i in issues]
    assert "auto_physical_damage_symbols_missing" in codes


def test_unspecified_symbols_do_not_manufacture_a_physical_damage_gap():
    """A grid we read but could not attribute is evidence, not a gap."""
    facts = {"auto_covered_symbols": [1, 7]}
    issues = _check_auto_symbol_to_exposure_alignment(facts, CLIENT_FLAGS, {"ACORD_127"})
    assert [i for i in issues if i["code"] == "auto_physical_damage_symbols_missing"] == []


# ── The check we could never run before ───────────────────────────────────────

def test_scheduled_fleet_with_hired_only_symbol_is_a_hard_stop():
    """Owned trucks on the schedule, Symbol 8/9 liability: a real coverage hole."""
    facts = {
        "auto_covered_symbols": [{"coverage": "liability", "symbols": [8, 9]}],
        "auto_vin_schedule": [{"vin": "A"}, {"vin": "B"}],
    }
    issues = _check_auto_owned_fleet_symbol_gap(facts, CLIENT_FLAGS, {"ACORD_127"})
    assert len(issues) == 1
    assert issues[0]["type"] == "hard_stop"
    assert "2 scheduled vehicle" in issues[0]["message"]


def test_fleet_gap_silent_on_unrecognised_symbol():
    facts = {
        "auto_covered_symbols": [{"coverage": "liability", "symbols": [19]}],
        "auto_vin_schedule": [{"vin": "A"}],
    }
    assert _check_auto_owned_fleet_symbol_gap(facts, CLIENT_FLAGS, {"ACORD_127"}) == []


def test_fleet_gap_silent_without_a_schedule():
    facts = {"auto_covered_symbols": [{"coverage": "liability", "symbols": [8]}]}
    assert _check_auto_owned_fleet_symbol_gap(facts, CLIENT_FLAGS, {"ACORD_127"}) == []


# ── The five phantom facts must never come back ───────────────────────────────

def test_no_check_reads_a_fact_nothing_writes():
    """Guard against the root cause, not just this instance.

    These five keys were read by cross_form_validator and sqs_service and
    written by nothing. Any future reference means the same class of permanent
    false positive has been reintroduced.
    """
    import services.cross_form_validator as cfv
    import services.sqs_service as sqs

    phantom = [
        "hired_auto_symbol", "non_owned_symbol",
        "auto_physical_damage_comp_symbol", "auto_physical_damage_coll_symbol",
        "drive_other_car_symbol",
    ]
    for module in (cfv, sqs):
        with open(module.__file__, encoding="utf-8") as fh:
            src = fh.read()
        for key in phantom:
            assert f'"{key}"' not in src, (
                f"{os.path.basename(module.__file__)} reads {key!r}, which no code "
                f"ever writes - see test docstring"
            )


# ── Stamping ──────────────────────────────────────────────────────────────────

def test_symbol_checkboxes_stamp_from_the_document():
    from services.pdf_service import _derive_symbol_indicator as d

    facts = {"auto_covered_symbols": [{"coverage": "liability", "symbols": [1]}]}
    assert d("Vehicle_BusinessAutoSymbol_OneIndicator_A", facts) == "Yes"
    assert d("Vehicle_BusinessAutoSymbol_EightIndicator_A", facts) == "No"
    assert d("Vehicle_BusinessAutoSymbol_OtherSymbolIndicator_A", facts) == "No"


def test_symbol_checkboxes_untouched_when_no_symbols_captured():
    """None keeps the box gap-fill eligible - a document we could not read must
    not be declared to have no coverage."""
    from services.pdf_service import _derive_symbol_indicator as d
    assert d("Vehicle_BusinessAutoSymbol_OneIndicator_A", {}) is None


def test_a_business_auto_policy_does_not_answer_the_truckers_grid():
    from services.pdf_service import _derive_symbol_indicator as d
    facts = {"auto_covered_symbols": [1]}
    assert d("Vehicle_TruckersSymbol_FortyOneIndicator_A", facts) is None
    assert d("Vehicle_MotorCarrierSymbol_SixtyOneIndicator_A", facts) is None


def test_other_symbol_box_ticks_for_iso_5_and_19():
    from services.pdf_service import _derive_symbol_indicator as d
    facts = {"auto_covered_symbols": [{"coverage": "liability", "symbols": [1, 19]}]}
    assert d("Vehicle_BusinessAutoSymbol_OtherSymbolIndicator_A", facts) == "Yes"


def test_any_auto_box_on_certificate_and_umbrella():
    """A Symbol 1 policy whose certificate leaves ANY AUTO blank understates
    coverage to whoever relies on it."""
    from services.pdf_service import _derive_symbol_indicator as d
    sym1 = {"auto_covered_symbols": [{"coverage": "liability", "symbols": [1]}]}
    sym7 = {"auto_covered_symbols": [{"coverage": "liability", "symbols": [7]}]}
    for field in ("Vehicle_AnyAutoIndicator_A",
                  "UnderlyingCoverage_Coverage_AnyAutoIndicator_A"):
        assert d(field, sym1) == "Yes"
        assert d(field, sym7) == "No"
        assert d(field, {}) is None


def test_vehicle_rows_inherit_the_policy_level_symbol():
    """One "Comprehensive 07" on the dec page applies to every scheduled truck."""
    from services.pdf_service import _resolve_schedule_row as r

    facts = {
        "auto_vin_schedule": [{"vin": "A"}, {"vin": "B"}],
        "auto_covered_symbols": [
            {"coverage": "comprehensive", "symbols": [7]},
            {"coverage": "collision", "symbols": [7]},
        ],
    }
    assert r("Vehicle_ComprehensiveSymbolCode_A", facts) == "7"
    assert r("Vehicle_ComprehensiveSymbolCode_B", facts) == "7"
    assert r("Vehicle_CollisionSymbolCode_B", facts) == "7"
    # Row beyond the schedule stays blank, as every other column does.
    assert r("Vehicle_ComprehensiveSymbolCode_C", facts) is None


def test_row_level_symbol_beats_the_policy_level_one():
    from services.pdf_service import _resolve_schedule_row as r
    facts = {
        "auto_vin_schedule": [{"vin": "A", "comp_symbol": "2"}, {"vin": "B"}],
        "auto_covered_symbols": [{"coverage": "comprehensive", "symbols": [7]}],
    }
    assert r("Vehicle_ComprehensiveSymbolCode_A", facts) == "2"
    assert r("Vehicle_ComprehensiveSymbolCode_B", facts) == "7"


def test_competing_policy_level_symbols_leave_the_cell_blank():
    """Two comprehensive symbols means the fleet varies by row. Do not pick one."""
    from services.pdf_service import _resolve_schedule_row as r
    facts = {
        "auto_vin_schedule": [{"vin": "A"}],
        "auto_covered_symbols": [{"coverage": "comprehensive", "symbols": [2, 7]}],
    }
    assert r("Vehicle_ComprehensiveSymbolCode_A", facts) is None


def test_schedule_symbol_columns_bind_to_live_acord_fields():
    from services.schedule_capture import SCHEDULE_DEFS
    from services.pdf_service import _SCHEDULE_REGISTRY

    cols = {c["key"] for c in SCHEDULE_DEFS["auto_vin_schedule"]["columns"]}
    assert {"comp_symbol", "coll_symbol"} <= cols

    live = set(_schema("ACORD_127"))
    for base, defn in _SCHEDULE_REGISTRY.items():
        if defn.list_key == "auto_vin_schedule" and defn.sub_key in {
            "comp_symbol", "coll_symbol", "symbol"
        }:
            assert f"{base}_A" in live, f"{base}_A is not a real ACORD 127 field"


# ── Registry wiring ───────────────────────────────────────────────────────────

def test_every_new_code_is_registered():
    from services.issue_registry import CLUSTER_MAP, RESOLUTION_MAP

    for code in ("auto_symbols_not_captured",
                 "auto_owned_fleet_not_covered_by_symbol",
                 "auto_hired_nonowned_symbols_missing",
                 "auto_physical_damage_symbols_missing"):
        assert code in CLUSTER_MAP
        assert code in RESOLUTION_MAP


def test_symbol_issues_are_resolvable_by_entering_the_symbols():
    """The client asked for Resolve to TRANSFER the symbols, not to be a
    read-only acknowledgement. These were _R_NONE before."""
    from services.issue_registry import RESOLUTION_MAP
    for code in ("auto_symbols_not_captured",
                 "auto_hired_nonowned_symbols_missing",
                 "auto_physical_damage_symbols_missing"):
        res = RESOLUTION_MAP[code]
        assert res["mode"] == "field"
        assert res["facts"] == ["auto_covered_symbols"]


def test_producer_answer_validation():
    from services.fact_registry import FACT_REGISTRY
    validate = FACT_REGISTRY["auto_covered_symbols"]["validate"]
    assert validate("Liability 1, Comprehensive 7, Collision 7") is True
    assert validate("1") is True
    assert validate("see policy") is False
    assert validate("") is False
