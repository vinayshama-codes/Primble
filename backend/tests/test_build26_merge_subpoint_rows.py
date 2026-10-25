"""Same-pillar Recommendations rows each worth under a point merge into ONE row
(owner, 24 Oct 2026; services/review_plan.merge_subpoint_rows)."""
from services import review_plan as RP


def _item(n, pillar, gain, fact):
    return {"id": f"rec:{n}", "kind": "rec", "row_index": n, "pillar": pillar, "gain": gain,
            "keys": [f"fact:{fact}"], "held_by": None}


def _pkg(rows):
    return {"package_sqs_score": 90, "top_recommendations": rows}


ROWS = [
    {"pillar": "property_integrity", "field": "hydrant_distance", "action": "Distance to the nearest fire hydrant"},
    {"pillar": "property_integrity", "field": "fire_department_type", "action": "Fire department type"},
    {"pillar": "property_integrity", "field": "roof_year", "action": "Roof year"},
    {"pillar": "exposure_consistency", "field": "num_employees", "action": "Employees"},
]


def test_two_subpoint_rows_in_one_pillar_merge():
    plan = {"items": [_item(0, "property_integrity", 0.5, "hydrant_distance"),
                      _item(1, "property_integrity", 0.5, "fire_department_type"),
                      _item(2, "property_integrity", 2.0, "roof_year"),
                      _item(3, "exposure_consistency", 0.4, "num_employees")]}
    out = RP.merge_subpoint_rows(_pkg(ROWS), plan)
    rows = out["top_recommendations"]
    assert len(rows) == 3
    m = rows[0]
    assert m["action"] == "Distance to the nearest fire hydrant + Fire department type"
    assert m["merged_fields"] == ["hydrant_distance", "fire_department_type"]
    assert m["resolution"]["mode"] == "field"
    assert m["resolution"]["facts"] == ["hydrant_distance", "fire_department_type"]
    # The >=1 row and the lone sub-point row stay as they are.
    assert rows[1] == ROWS[2] and rows[2] == ROWS[3]


def test_lone_subpoint_row_and_whole_point_rows_unchanged():
    plan = {"items": [_item(0, "property_integrity", 0.5, "hydrant_distance"),
                      _item(1, "property_integrity", 1.0, "fire_department_type"),
                      _item(2, "property_integrity", 2.0, "roof_year"),
                      _item(3, "exposure_consistency", 0.4, "num_employees")]}
    assert RP.merge_subpoint_rows(_pkg(ROWS), plan) is None


def test_held_or_mirrored_rows_never_merge():
    a = _item(0, "property_integrity", 0.5, "hydrant_distance")
    b = dict(_item(1, "property_integrity", 0.5, "fire_department_type"), mirror_of="kd:x")
    assert RP.merge_subpoint_rows(_pkg(ROWS), {"items": [a, b]}) is None


def test_merged_row_keeps_its_window_through_the_fix_route():
    from services.review_recommendations import fix_route_for_row
    row = dict(ROWS[0], merged_fields=["hydrant_distance", "fire_department_type"])
    res = fix_route_for_row(row, {})
    assert res["mode"] == "field" and res["facts"] == ["hydrant_distance", "fire_department_type"]


def test_merged_plan_number_is_the_joint_move_and_sum_is_100_minus_score(monkeypatch):
    """Through the real plan: two half-point rows in one pillar weigh as one +1,
    and the plan still adds up to 100 - score."""
    class FakeSim:
        def __init__(self, row):
            self.session = {"facts": {}}
            self.score = 98.0
        def measure(self):
            return self.score, self.score, None, None
        def answer(self, fact, value):
            if fact in self.session["facts"]:
                return False
            self.session["facts"][fact] = value
            self.score += 0.5
            return True
    monkeypatch.setattr(RP, "_Sim", FakeSim)
    rows = [{"pillar": "property_integrity", "field": f, "action": f,
             "resolution": {"mode": "field", "facts": [f]}} for f in ("a_fact", "b_fact", "c_fact", "d_fact")]
    rows[2]["pillar"] = rows[3]["pillar"] = "exposure_consistency"
    pkg = {"package_sqs_score": 98, "top_recommendations": rows}
    plan = RP.build_review_plan({"facts": {}}, pkg, None, None)
    merged = RP.merge_subpoint_rows(pkg, plan)
    assert merged is not None and len(merged["top_recommendations"]) == 2
    plan2 = RP.build_review_plan({"facts": {}}, merged, None, None)
    recs = [i for i in plan2["items"] if i["kind"] == "rec"]
    assert [i["points"] for i in recs] == [1, 1]
    assert not any(i["under"] for i in recs)
    assert sum(i["points"] for i in plan2["items"]) + plan2["left"] == 100 - 98


# ── Review fixes (24 Oct 2026) ───────────────────────────────────────────────
def test_merged_window_asks_each_question_not_whichever_applies():
    """Each merged row moves points on its own, so the window names a blank box
    and saves a partial answer as progress (`resolution.needs`), never "fill
    whichever applies"."""
    res = RP.merged_resolution(["distance_to_hydrant", "fire_department_type"])
    assert res["facts"] == ["distance_to_hydrant", "fire_department_type"]
    assert res["needs"] == [["distance_to_hydrant"], ["fire_department_type"]]
    assert res["controls"]["fire_department_type"]["control"] == "select"
    assert res["controls"]["distance_to_hydrant"]["control"] == "number"
    # A single field is never a merged window.
    assert "needs" not in RP.merged_resolution(["distance_to_hydrant"])


import json as _json
import shutil as _shutil
import subprocess as _subprocess
from pathlib import Path as _Path

import pytest as _pytest

_REC = _Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils" / "recommendations.js"


@_pytest.mark.skipif(_shutil.which("node") is None, reason="node is not installed")
def test_partial_save_of_a_merged_row_is_open_not_fixed(tmp_path):
    """One box typed, one left blank: the other question is listed again as a
    row of its own under a NEW id. The merged row is still open - never filed
    "resolved" beside its own unanswered question."""
    script = tmp_path / "check.mjs"
    script.write_text(
        f"import * as R from {_json.dumps(_REC.as_uri())};\n"
        "const res = {mode: 'field', facts: ['distance_to_hydrant', 'fire_department_type']};\n"
        "const merged = {pillar: 'property_integrity', field: 'distance_to_hydrant', action: 'a + b', points_available: 2,\n"
        "  merged_fields: ['distance_to_hydrant', 'fire_department_type'], resolution: res, answer_mode: 'field'};\n"
        "const lone = (f) => ({pillar: 'property_integrity', field: f, action: f, points_available: 1, answer_mode: 'field',\n"
        "  resolution: {mode: 'field', facts: [f]}});\n"
        "const id = R.scoreItems({top_recommendations: [merged]})[0].id;\n"
        "const out = {id};\n"
        "out.partial = R.recommendationFixState('score', id, {packageSqs: {top_recommendations: [lone('fire_department_type')]}});\n"
        "out.both = R.recommendationFixState('score', id, {packageSqs: {top_recommendations: [lone('roof_year')]}});\n"
        "out.single = R.recommendationFixState('score', R.scoreItems({top_recommendations: [lone('roof_year')]})[0].id,\n"
        "  {packageSqs: {top_recommendations: [lone('fire_department_type')]}});\n"
        "console.log(JSON.stringify(out));\n", encoding="utf-8")
    run = _subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    o = _json.loads(run.stdout)
    assert o["id"] == "score:property_integrity:fact:distance_to_hydrant|fact:fire_department_type"
    assert o["partial"] == "open"
    assert o["both"] == "fixed"
    assert o["single"] == "fixed"


def test_a_half_saved_merged_row_stays_one_row_with_every_question():
    """Owner, 24 Oct 2026: after one box of a merged row is saved, opening it
    again shows BOTH questions (the answered one filled in and editable), under
    the id the first save used - never a lone row hiding the first answer."""
    saved = RP.saved_merged_groups(
        ["rec:score:property_integrity:fact:hydrant_distance|fact:fire_department_type",
         "rec:score:property_integrity:fact:roof_year",            # not a merged row
         "kd:FEIN / Tax ID"])
    assert saved == {"property_integrity": [["hydrant_distance", "fire_department_type"]]}
    rows = [ROWS[1], ROWS[2], ROWS[3]]                               # hydrant answered
    plan = {"items": [_item(0, "property_integrity", 0.5, "fire_department_type"),
                      _item(1, "property_integrity", 2.0, "roof_year"),
                      _item(2, "exposure_consistency", 0.4, "num_employees")]}
    out = RP.merge_subpoint_rows(_pkg(rows), plan, saved)
    m = out["top_recommendations"][0]
    assert m["merged_fields"] == ["hydrant_distance", "fire_department_type"]
    assert m["resolution"]["facts"] == ["hydrant_distance", "fire_department_type"]
    assert out["top_recommendations"][1:] == [ROWS[2], ROWS[3]]
    # Nothing saved before -> the lone row is untouched.
    assert RP.merge_subpoint_rows(_pkg(rows), plan, {}) is None
    # Both answered -> nothing open -> nothing to keep.
    assert RP.merge_subpoint_rows(_pkg([ROWS[2], ROWS[3]]),
                                  {"items": [_item(0, "property_integrity", 2.0, "roof_year")]}, saved) is None
