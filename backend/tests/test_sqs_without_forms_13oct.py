"""The SQS without forms, and with them (owner + Brent, 13 Oct 2026).

Owner: "brent and i both agreed ... sqs can exist without the forms ... this should reach 100
... and after forms are generated then we should be able to recalculate the score" and "i need
100 after forms as well, if they answer everything".

Measured on the owner's package 18f6914f before this change: every pre-form item answered
scored 94 - Structural 92 (a Form Fill Rate of 71 measured on RECOMMENDED forms nobody had
generated), Exposure 95 (a radius of operation the auto policy prints as "LOCAL" on every
vehicle row, unread) and Property 90 (distance to hydrant, fire department type) - and none of
the three could be answered anywhere: the score rows said "Incomplete: Auto Completeness" /
"Improve property integrity" with no box behind them. After forms, a document-verified AI value
weighed 0.85 and "Please verify" rows had no way to be confirmed, so 100 was unreachable too.

Now:
  * before forms Structural is the no-forms formula (Tier 1 53.3 / Tier 2 46.7) and a check
    whose only fix is choosing a form is a FORM CHOICE - outside the number, listed where forms
    are chosen;
  * every Exposure / Property deduction is its own row naming the box that answers it, read
    off the same items the pillar is scored from (`exposure_deduction_items`,
    `property_gap_items`);
  * the radius class a vehicle rating table prints is read (`read_vehicle_radius_class`);
  * after forms a source-verified AI value weighs 1.00, every filled box below full weight is a
    confirmable "Please verify" row, and each post-form score carries `without_forms`.
"""
from __future__ import annotations

import itertools
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from services import sqs_service as S
from services.answer_options import OTHER, options_for
from services.answer_routing import answer_mode
from services.coverage_evidence import AUTO_RADIUS_READING_KEY, auto_radius_known, radius_stated
from services.cross_form_validator import defer_form_choices, is_form_choice, split_cross_form_issues
from services.extraction_service import read_vehicle_radius_class, vehicle_radius_classes
from services.fact_registry import FACT_REGISTRY
from services.issue_registry import grouped_with_package_caps

_FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _env(v, source="producer"):
    return {"value": v, "source": source, "confidence": "producer"}


# ══ Before forms: Structural without a form fill ══════════════════════════════
def _complete_facts():
    """Tier 1 + Tier 2 all present."""
    f = {k: _env("x") for k in list(S.TIER1_FIELDS) + list(S.TIER2_FIELDS)}
    f.update({"applicant_name": _env("Acme LLC"), "effective_date": _env("01/01/2027"),
              "expiration_date": _env("01/01/2028"), "contact_name": _env("Dana"),
              "num_employees": _env("41"), "naics_code": _env("238210"),
              "total_revenue": _env("$5,000,000"), "years_in_business": _env("17"),
              "fein": _env("12-3456789"), "operations_description": _env("Electrical contractor")})
    return f


def _structural_rows(pkg):
    return {r.get("key") or r.get("component"): r for r in (pkg.get("score_trace") or {}).get("structural") or []}


def test_form_fill_false_ignores_the_form_results_fill():
    # 23 Oct 2026 (Brent, Z34-1 #1): no fill slice is the DEFAULT on every path;
    # the old slice survives only as the explicit `form_fill=True` reversal. The
    # TEST relied on the old default and was updated to name it; the code is right.
    facts, flags = _complete_facts(), {}
    results = [{"form_id": "ACORD_125", "confidence_fill_rate": 40}]
    common = dict(facts=facts, flags=flags, form_results=results, cross_issues=[],
                  hard_stops=[], soft_stops=[], session_data={}, _probe=True)
    with_fill = S.calculate_package_sqs(**common, form_fill=True)
    without = S.calculate_package_sqs(**common, form_fill=False)
    assert S.calculate_package_sqs(**common)["package_sqs_score"] == without["package_sqs_score"]
    assert len((with_fill["score_trace"] or {})["structural"]) == 3          # tier1, tier2, fill
    rows = without["score_trace"]["structural"]
    assert len(rows) == 2 and all("fill" not in str(r).lower() for r in rows), rows
    assert without["pillars"]["structural_completeness"] >= with_fill["pillars"]["structural_completeness"]
    assert without["without_forms"] is None                                   # nothing to compare


def test_pre_form_score_is_the_no_forms_recipe(monkeypatch):
    seen = {}
    real = S.calculate_package_sqs

    def spy(**kw):
        seen.update(kw)
        return real(**kw)

    monkeypatch.setattr(S, "calculate_package_sqs", spy)
    session = {"facts": _complete_facts(), "flags": {},
               "recommendations": [{"form_id": "ACORD_125"}], "docs": []}
    S.score_package_pre_generation(session, "sid", "uid")
    assert seen.get("form_fill") is False


def test_a_post_form_score_carries_the_score_without_forms():
    # 23 Oct 2026 (Brent, Z34-1 #1): one number before and after forms, so a
    # post-form score carries no second number by default (the TEST pinned the old
    # "Without forms X · With forms Y" pair and was updated). The comparison is kept
    # only on the explicit `form_fill=True` reversal path.
    facts = _complete_facts()
    session = {"facts": facts, "flags": {}, "recommendations": [{"form_id": "ACORD_125"}], "docs": []}
    kw = dict(facts=facts, flags={}, form_results=[{"form_id": "ACORD_125", "confidence_fill_rate": 80}],
              cross_issues=[], hard_stops=[], soft_stops=[], session_data=session)
    assert S.calculate_package_sqs(**kw)["without_forms"] is None
    pkg = S.calculate_package_sqs(**kw, form_fill=True)
    wf = pkg["without_forms"]
    assert isinstance(wf, dict) and wf["score"] is not None
    assert wf["score"] >= pkg["package_sqs_score"]       # the 80% fill costs only with forms
    # Probes never pay for it (they only need the number).
    probe = S.calculate_package_sqs(**kw, _probe=True, form_fill=True)
    assert probe["without_forms"] is None


# ══ A form choice is not a gap in the submission ══════════════════════════════
_ACORD25 = {"type": "soft_warning", "code": "certificate_requested_but_acord25_missing",
            "message": "A certificate of liability was requested (certificate holder detected) but ACORD 25 "
                       "is not in the selected forms. Add ACORD 25 to satisfy the request.",
            "forms": ["ACORD_25"], "resolution": {"mode": "none", "add_forms": ["ACORD_25"]}}
_NARR101 = {"type": "soft_warning", "code": "acord101_required", "message": "Explain it on ACORD 101.",
            "forms": ["ACORD_101"], "resolution": {"mode": "narrative", "add_forms": ["ACORD_101"]}}
_TYPED = {"type": "soft_warning", "code": "auto_um_uim_not_specified", "message": "UM/UIM not specified.",
          "forms": ["ACORD_127"], "resolution": {"mode": "field", "facts": ["auto_um_uim_limit"]}}


def test_only_a_form_only_fix_is_a_form_choice():
    assert is_form_choice(_ACORD25)
    assert not is_form_choice(_NARR101)            # a narrative answers it - it stays a stop
    assert not is_form_choice(_TYPED)
    assert not is_form_choice({"type": "soft_warning", "resolution": {"mode": "none"}})
    assert not is_form_choice(None)


def _listed(msg, stops):
    """The split appends "(Affects: ... Fix: ...)" to each sentence."""
    return any(str(m).startswith(msg) for m in stops)


def test_deferring_takes_a_form_choice_out_of_both_stop_lists():
    out = defer_form_choices([_ACORD25, _NARR101, _TYPED])
    hard, soft, adv = split_cross_form_issues(out)
    assert not _listed(_ACORD25["message"], soft) and not _listed(_ACORD25["message"], hard)
    assert _listed(_NARR101["message"], soft) and _listed(_TYPED["message"], soft)
    assert out[0]["form_choice"] is True and out[0]["type"] == "advisory"
    assert _ACORD25["type"] == "soft_warning"           # a copy - the caller's issue is untouched


def test_stops_now_defers_form_choices_before_and_after_forms(monkeypatch):
    """25 Oct 2026 (Brent 23 Oct: the package score is independent of the forms):
    a form choice is never a stop - before forms AND after (generating without
    ACORD 186 dropped a finished package 100 -> 85). A real warning still is."""
    import services.stops_now as SN
    monkeypatch.setattr(SN, "cross_form_run", lambda *_a, **_k: [dict(_ACORD25), dict(_TYPED)])
    session = {"facts": {}, "flags": {}, "docs": [], "recommendations": [{"form_id": "ACORD_125"}]}
    for pre_form in (True, False):
        st = SN.stops_now(session, ["ACORD_125"], pre_form=pre_form)
        assert not _listed(_ACORD25["message"], st["soft"]) and _listed(_TYPED["message"], st["soft"])
        assert any(i.get("form_choice") for i in st["cross_issues"])


def test_the_review_lists_a_form_choice_apart_from_the_warnings():
    structured = [{"code": _ACORD25["code"], "severity": "soft_warning", "message": _ACORD25["message"],
                   "forms": ["ACORD_25"], "resolution": dict(_ACORD25["resolution"])},
                  {"code": _TYPED["code"], "severity": "soft_warning", "message": _TYPED["message"],
                   "forms": ["ACORD_127"], "resolution": dict(_TYPED["resolution"])}]
    # A row stored before 13 Oct still lists the sentence in the soft list: the package decides.
    soft = [_ACORD25["message"], _TYPED["message"]]
    pkg = {"form_choices": [{"code": _ACORD25["code"], "message": _ACORD25["message"],
                             "forms": ["ACORD_25"], "add_forms": ["ACORD_25"]}]}
    view = grouped_with_package_caps(structured, [], soft, pkg)
    shown = [it["message"] for tier in view["warnings"].values() for c in tier for it in (c.get("items") or [c])]
    assert _ACORD25["message"] not in " ".join(str(m) for m in shown)
    assert view["counts"]["warnings"] == 1
    assert [c["code"] for c in view["form_choices"]] == [_ACORD25["code"]]
    assert view["form_choices"][0]["resolution"]["add_forms"] == ["ACORD_25"]
    # After forms (no `form_choices` on the package) nothing changes: it is a warning.
    after = grouped_with_package_caps(structured, [], soft, {})
    assert after["counts"]["warnings"] == 2 and after["form_choices"] == []


# ══ Every deduction is a question ═════════════════════════════════════════════
_FLAG_SETS = [
    {"has_general_liability": True},
    {"has_workers_comp": True, "wc_multi_state": True},
    {"has_auto_coverage": True},
    {"is_contractor": True},
    {"has_general_liability": True, "has_workers_comp": True, "has_auto_coverage": True,
     "is_contractor": True, "has_property_coverage": True},
]


@pytest.mark.parametrize("flags", _FLAG_SETS)
@pytest.mark.parametrize("n_hard,n_warn", [(0, 0), (1, 0), (0, 3), (2, 2)])
def test_exposure_items_are_the_score(flags, n_hard, n_warn):
    facts = {"num_employees": _env("12"), "auto_vin_schedule": _env([{"year": "2020"}])}
    hard = [{"type": "hard_stop", "message": f"h{i}"} for i in range(n_hard)]
    warn = [{"type": "soft_warning", "message": f"w{i}"} for i in range(n_warn)]
    items = S.exposure_deduction_items(facts, flags, hard, warn)
    score, subs = S._calculate_exposure_consistency(facts, flags, hard, warn)
    assert score == max(0, 100 - sum(i["points"] for i in items))
    for bucket, sub in subs.items():
        assert sub == max(0, 100 - sum(i["points"] for i in items if i["bucket"] == bucket))


def test_every_exposure_item_with_a_box_routes_to_an_answer():
    flags = {"has_general_liability": True, "has_workers_comp": True, "wc_multi_state": True,
             "has_auto_coverage": True, "is_contractor": True}
    # (19 Oct 2026, Brent: missing details are Completeness) the boxes moved with them;
    # only the cross-form details are answered by their own cards.
    detail = [{"type": "soft_warning", "message": "a cross-form check asking for a detail"}]
    items = S.completeness_deduction_items({}, flags, [], detail)
    assert items, "the fixture must raise deductions"
    assert any(not it["fact"] for it in items), "and reach the box-less branch"
    for it in items:
        if it["fact"]:
            mode = answer_mode(it["fact"]).get("mode")
            assert mode in ("field", "schedule", "narrative"), (it, mode)
        else:
            assert it["bucket"] == "cross_form_details", it
    # (19 Oct 2026, Brent: Exposure = conflicts only) a disagreeing figure has its box;
    # a coverage decision and the cross-form conflicts have none.
    facts = {"num_employees": _env("12"), "auto_vin_schedule": _env([{"year": "2020"}]),
             "total_revenue": _env("$10,000,000"), "total_payroll": _env("$25,000")}
    conflict = [{"type": "soft_warning", "code": "location_address_mismatch", "message": "c"}]
    items = S.exposure_deduction_items(facts, {"is_contractor": True}, [], conflict)
    assert {it["bucket"] for it in items} == set(S._EXPOSURE_BUCKETS) - {"operations_description"}
    for it in items:
        if it["fact"]:
            mode = answer_mode(it["fact"]).get("mode")
            assert mode in ("field", "schedule", "narrative"), (it, mode)
        else:
            assert it["bucket"] in ("payroll_employee_information", "coverage_information",
                                    "cross_document_consistency"), it


@pytest.mark.parametrize("present", [frozenset(p) for n in range(0, 5) for p in itertools.combinations(
    ["locations", "occupancy_type", "construction_type", "property_building_value", "year_built",
     "distance_to_hydrant", "fire_department_type"], n)][:60])
def test_property_items_sum_to_the_pillar_gap(present):
    facts = {k: _env("1999" if k == "year_built" else "x") for k in present}
    score = S._calculate_cope_score(facts, {"has_property_coverage": True})
    items = S.property_gap_items(facts, {"has_property_coverage": True})
    assert score == max(0, 100 - sum(i["points"] for i in items))
    for it in items:
        assert answer_mode(it["fact"]).get("mode") in ("field", "schedule"), it


def test_no_property_line_no_property_items():
    assert S.property_gap_items({}, {}) == []
    assert S._calculate_cope_score({}, {}) == 100


def test_gap_rows_add_up_to_the_pillar_and_name_their_box():
    items = [{"points": 5, "fact": "distance_to_hydrant", "label": "Distance to the nearest fire hydrant"},
             {"points": 5, "fact": "fire_department_type", "label": "Fire department type"},
             {"points": 8, "fact": None, "label": "Vehicles are listed but no auto coverage is carried"}]
    rows = S._gap_rows("property_integrity", 82, items, 0.2)
    assert [r["field"] for r in rows] == ["distance_to_hydrant", "fire_department_type", None]
    assert round(sum(r["points_available"] for r in rows), 1) == round(18 * 0.2, 1)
    assert rows[-1]["closes_with"] == "review"


def test_the_package_lists_the_owners_last_three_questions():
    """18f6914f's shape after every key detail: Exposure short a radius, Property short the
    hydrant and fire department - each its own row with its box (they were unanswerable)."""
    facts = _complete_facts()
    facts.update({"auto_vin_schedule": _env([{"year": "2001", "make": "CHEVROLET"}]),
                  "auto_drivers": _env([{"name": "Marcus Delgado"}]),
                  "auto_garaging_addresses": _env(["Denver CO 80221"]),
                  "auto_vehicle_use": _env("service"), "auto_liability_limit": _env("$1,000,000"),
                  "auto_covered_symbols": _env("1"),
                  "locations": _env([{"address_line1": "4800 Washington St"}]),
                  "occupancy_type": _env("Office"), "construction_type": _env("Frame - wood construction"),
                  "property_building_value": _env("$500,000"), "year_built": _env("1999"),
                  "roof_year": _env("2015"), "sprinkler_system": _env("No - not sprinklered"),
                  "fire_protection_class": _env("Protection Class 3"),
                  "business_income_limit": _env("$250,000"), "period_of_restoration": _env("12 months")})
    flags = {"has_auto_coverage": True, "has_property_coverage": True, "has_workers_comp": True}
    facts.update({"wc_payroll": _env("$2,626,500"), "wc_class_codes": _env([{"code": "5190", "state": "CO"}]),
                  "wc_xmod": _env("1.08"), "wc_payroll_period": _env("Annual - the figure covers a full year"),
                  "wc_officer_exclusions": _env("No - all owners and officers are included")})
    pkg = S.calculate_package_sqs(facts=facts, flags=flags, form_results=[], cross_issues=[],
                                  hard_stops=[], soft_stops=[], session_data={"docs": []}, form_fill=False)
    fields = {r.get("field") for r in pkg["top_recommendations"]}
    assert {"auto_radius_of_operation", "distance_to_hydrant", "fire_department_type"} <= fields
    # (19 Oct 2026, Brent: missing details are Completeness) the radius is Structural's now.
    assert pkg["pillars"]["structural_completeness"] < 100
    # Answering the three closes the score.
    answered = dict(facts, auto_radius_of_operation=_env("Local (up to 50 miles)"),
                    distance_to_hydrant=_env("500"), fire_department_type=_env("Professional"))
    pkg2 = S.calculate_package_sqs(facts=answered, flags=flags, form_results=[], cross_issues=[],
                                   hard_stops=[], soft_stops=[], session_data={"docs": []}, form_fill=False)
    assert pkg2["pillars"]["structural_completeness"] == 100, pkg2["top_recommendations"]
    assert pkg2["pillars"]["exposure_consistency"] == 100, pkg2["top_recommendations"]
    assert pkg2["pillars"]["property_integrity"] == 100


def test_a_coverage_decision_is_a_row_without_a_box():
    """41 employees and no workers comp line: no box answers that - a review row, never a
    typed box the server would refuse."""
    items = S.exposure_deduction_items({"num_employees": _env("41")}, {}, [], [])
    assert [(i["bucket"], i["fact"]) for i in items] == [("payroll_employee_information", None)]
    rows = S._gap_rows("exposure_consistency", 92, items, 0.25)
    assert rows[0]["field"] is None and rows[0]["closes_with"] == "review"


def test_a_choice_list_question_is_probed_with_a_choice():
    answer, valid = S._package_probe_answer("auto_radius_of_operation")
    assert valid and radius_stated(answer), answer


# ══ The radius a rating table prints ══════════════════════════════════════════
_TABLE = ("Size GVW, GCW\n"
          "Radius of Business or Vehicle Seating Primary Rating Primary Rating Factor Secondary Rating\n"
          "Veh #Operation Use Zone Capacity Factor - Liability Physical Damage Factor Class\n"
          "001 LOCAL SERVICE 10 01483\n002 LOCAL SERVICE 10 01483\n004 10 7398\n"
          "005 LOCAL SERVICE 10 01483\nCoverages - Premium, Limits and Deductibles\n")


def test_the_radius_class_is_read_off_its_own_column():
    assert vehicle_radius_classes([{"text": _TABLE}]) == {"LOCAL"}
    mf = {}
    assert read_vehicle_radius_class(mf, [{"text": _TABLE}]) == "LOCAL"
    assert mf[AUTO_RADIUS_READING_KEY] == "LOCAL" and auto_radius_known(mf)


@pytest.mark.parametrize("text", [
    "Item 2. Policy Period From: 01-01-2025 (12:01 AM local time at the address shown in Item 1.)",
    "001 LOCAL SERVICE 10 01483\n002 LOCAL SERVICE 10 01483",                 # no header names the radius
    "Business Use\nVeh # Operation Use\n001 LOCAL SERVICE 10",                # header without "radius"
])
def test_no_radius_without_a_radius_column(text):
    assert vehicle_radius_classes([{"text": text}]) == set()


def test_two_radius_classes_state_no_one_radius():
    two = _TABLE.replace("005 LOCAL", "005 INTERMEDIATE")
    mf = {}
    assert vehicle_radius_classes([{"text": two}]) == {"LOCAL", "INTERMEDIATE"}
    assert read_vehicle_radius_class(mf, [{"text": two}]) is None and AUTO_RADIUS_READING_KEY not in mf


def test_a_stated_radius_is_never_overwritten():
    mf = {"auto_radius_of_operation": _env("50")}
    assert read_vehicle_radius_class(mf, [{"text": _TABLE}]) is None
    assert AUTO_RADIUS_READING_KEY not in mf
    excluded = [{"text": _TABLE, "excluded": True}]
    assert vehicle_radius_classes(excluded) == set()


def test_the_new_choice_lists_are_answers_the_scorer_and_validator_accept():
    radius = [o for o in options_for("auto_radius_of_operation") if o != OTHER]
    assert radius and all(radius_stated(o) for o in radius)
    fd = [o for o in options_for("fire_department_type") if o != OTHER]
    assert fd and all(FACT_REGISTRY["fire_department_type"]["validate"](o) for o in fd)
    assert options_for("auto_radius_of_operation")[-1] == OTHER


# ══ After forms: every filled box below full weight can be confirmed ══════════
def test_brents_weights_stand_and_a_found_value_can_still_reach_full_weight():
    """Brent's 24 Aug weights (1.00 / 0.85 / 0.50) stand - the owner reverted a
    same-day change to 1.00. 100 stays reachable after forms: a found value is a
    Please verify row, and a confirmed value is the producer's (1.00)."""
    from services.needs_attention import CONFIRMABLE_LABELS
    assert S.CONFIDENCE_SCORE["ai_verified"] == 0.85
    assert S.CONFIDENCE_SCORE["low_confidence"] == 0.50
    assert "ai_verified" in CONFIRMABLE_LABELS and "low_confidence" in CONFIRMABLE_LABELS
    mapped = {f"F{i}": "v" for i in range(10)}
    assert S.confidence_fill_rate(mapped, {f: "ai_verified" for f in mapped}) == 85
    assert S.confidence_fill_rate(mapped, {f: "producer" for f in mapped}) == 100


def test_an_unticked_checkbox_is_not_a_filled_box():
    assert S.confidence_fill_rate({"a": "Acme", "b": "Off", "c": "/Off"},
                                  {"a": "filled", "b": "missing_required", "c": None}) == 100


def test_every_filled_label_below_full_weight_has_a_route():
    """Anti-rot: a label the fill layer emits that weighs < 1.0 on a FILLED box is either a
    Please verify row a person can Confirm, a Data Consistency conflict, or excluded."""
    from services.needs_attention import CONFIRMABLE_LABELS
    from tests.test_confidence_score_covers_every_label import _harvest_labels
    for label in _harvest_labels():
        if label in S.FILL_RATE_EXCLUDED_LABELS:
            continue
        if S.CONFIDENCE_SCORE.get(label, 0.0) < 1.0:
            assert label in CONFIRMABLE_LABELS or label == "conflicted", label


def _form(confidence, mapped):
    return {"mapped": dict(mapped), "confidence": dict(confidence), "schema": {}, "sqs": {}}


def test_a_value_under_a_stale_required_label_is_please_verify():
    from services.needs_attention import needs_attention
    fr = _form({"Box_A": "missing_required", "Tick_A": "missing_required", "Ok_A": "filled"},
               {"Box_A": "0", "Tick_A": "Off", "Ok_A": "Acme"})
    rows = {r["field"]: r for r in needs_attention(fr, {}, "ACORD_125")}
    assert rows["Box_A"]["status"] == "verify" and rows["Box_A"]["value"] == "0"
    # It counts toward the score until confirmed - never "No score effect".
    assert rows["Box_A"]["score_text"] == "Counts in full once you confirm it"
    assert "Tick_A" not in rows or rows["Tick_A"]["status"] != "verify"
    assert "Ok_A" not in rows


# ══ Frontend pieces (pure helpers under node) ═════════════════════════════════
def _node(tmp_path, module, body):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / "check.mjs"
    script.write_text(f"import * as M from {json.dumps((_FRONT / 'utils' / module).as_uri())};\n"
                      + body + "\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_confirm_sends_each_rows_own_value_for_one_form(tmp_path):
    out = _node(tmp_path, "confirmValues.js", """
const rows = [
  {form_id: "ACORD_125", field: "A", status: "verify", value: "Acme"},
  {form_id: "ACORD_125", field: "A", status: "verify", value: "Acme"},
  {form_id: "ACORD_125", field: "B", status: "missing", value: null},
  {form_id: "ACORD_125", field: "C", status: "verify", value: ""},
  {form_id: "ACORD_126", field: "D", status: "verify", value: "x"},
];
console.log(JSON.stringify({
  one: M.confirmFieldUpdates("ACORD_125", rows),
  none: M.confirmFieldUpdates("ACORD_127", rows),
  picked: M.confirmableRows(rows).map(M.rowKey),
}));""")
    assert out["one"] == {"__form_id__": "ACORD_125", "A": "Acme"}
    assert out["none"] is None
    assert out["picked"] == ["ACORD_125:A", "ACORD_126:D"]


def test_the_screen_explains_the_move_at_generation(tmp_path):
    # 23 Oct 2026 (Brent, Z34-1 #1): the number no longer moves at generation, so
    # there is no move to explain - "Without forms X · With forms Y" is gone and the
    # forms' to-dos are the Forms ready meter (tests/test_build25_score.py). The
    # TEST pinned the removed line and was updated.
    out = _node(tmp_path, "scoreWithForms.js", """
console.log(JSON.stringify({
  gone: typeof M.formsEffect,
  meter: M.formsReady({forms: [{form_id: "ACORD_125", rows: [{status: "verify"}]}]}).overall.text,
}));""")
    assert out["gone"] == "undefined"
    assert out["meter"] == "Forms ready: 1 value to confirm · 0 boxes to fill"
    assert "—" not in out["meter"]


def test_form_choices_are_not_listed_before_forms(tmp_path):
    # 14 Oct 2026 (owner): before forms the Recommendations section is the score
    # only, so a form choice ("Add ACORD 25") is neither listed nor counted there;
    # the score still leaves it out before forms (defer_form_choices, unchanged).
    out = _node(tmp_path, "recommendations.js", """
const grouped = {form_choices: [{issue_id: "i1", code: "certificate_requested_but_acord25_missing",
  message: "Add ACORD 25.", resolution: {mode: "none", add_forms: ["ACORD_25"]}}]};
const open = M.buildRecommendations({groupedIssues: grouped, formsExist: false, tickedFormIds: []});
const after = M.buildRecommendations({groupedIssues: grouped, formsExist: true, tickedFormIds: []});
console.log(JSON.stringify({open: [open.choicesOpen, open.count, open.formChoices.length],
  after: after.formChoices.length}));""")
    assert out["open"] == [0, 0, 0]
    assert out["after"] == 0
