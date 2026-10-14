"""A pillar held at 0 by one missing value lists its rows with the gate named
(owner, 14 Oct 2026, live run 823d58a0).

Property Integrity is 0 until occupancy is entered (the COPE minimum) while its
parts score 28 / 60. Its other rows measured +0 or nothing, so the list showed
year built / roof year / protection class ("up to +1") and hid hydrant / fire
department / sprinkler - and none of them could move the score yet. Now every
row of a held pillar is listed with "Adds points once Occupancy type is answered".
The fixture is the replayed pre-form screen of that package (read-only).
"""
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
UTIL = ROOT / "frontend" / "src" / "utils" / "recommendations.js"
FIX = pathlib.Path(__file__).parent / "fixtures" / "held_pillar_823d58a0.json"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _model(tmp_path, screen):
    script = tmp_path / "m.mjs"
    script.write_text(
        f"import * as R from {json.dumps(UTIL.as_uri())};\n"
        f"const s = {json.dumps(screen)};\n"
        "const m = R.buildRecommendations({ packageSqs: s.package_sqs, groupedIssues: s.grouped_issues, "
        "keyDetails: s.key_details, attention: null, formsExist: false });\n"
        "console.log(JSON.stringify(m.score.map((i) => ({ d: i.detail, held: i.heldBy, p: i.points }))));",
        encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@needs_node
def test_every_held_property_row_is_listed_with_its_gate(tmp_path):
    rows = {r["d"]: r for r in _model(tmp_path, json.loads(FIX.read_text()))}
    for d in ("Year built", "Roof year", "Sprinkler system", "Fire protection class",
              "Distance to the nearest fire hydrant", "Fire department type"):
        assert d in rows, d
        assert rows[d]["held"] == "Occupancy type"
        assert rows[d]["p"] == {"points": 1, "exact": False}
    # the gate itself sits on the COPE hard stop, the period of restoration on its warning
    assert "Occupancy type" not in rows and "Period of restoration" not in rows
    # rows of live pillars are not held
    assert all(r["held"] is None for d, r in rows.items() if d.startswith(("No loss", "Narrative")))


@needs_node
def test_once_the_gate_is_answered_nothing_is_held(tmp_path):
    screen = json.loads(FIX.read_text())
    for r in screen["package_sqs"]["top_recommendations"]:
        if r.get("pillar") == "property_integrity":
            r["score"] = 90
            if r.get("field") == "occupancy_type":
                r["answer_gain"] = None
    rows = _model(tmp_path, screen)
    assert all(r["held"] is None for r in rows)


def test_the_row_names_its_gate():
    src = (ROOT / "frontend" / "src" / "components" / "form" / "review" / "Recommendations.jsx").read_text()
    assert "Adds points once {it.heldBy} is answered." in src
