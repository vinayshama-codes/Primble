"""The last points after forms are listed (14 Oct 2026, live run f83757cf).

The owner: "package score is 99/100 now and I can't see any warning or anything to
make it 100". The 99 was the Form Fill Rate slice (93%): 57 AI values on eight forms
nobody had confirmed (0.85 / 0.50 against a confirmed 1.00). The scorer said so in a
row with no fix window, and the Recommendations section lists only rows it can open,
so the page showed nothing. The row is now listed after forms - only while the forms'
needs-attention lists hold Please verify values, the one thing "Confirm all" can fix -
and "Open to fix" opens the form with the most of them.

REVERSED 23 Oct 2026 (Brent, Z34-1 #1: "Yes, this is acceptable"): the package score
is independent of the forms, so the fill rate is no slice of it and there is no
"last point on the forms" to list. The fill-rate row and the Overview's "your last
points are on the forms" notice are gone; the forms' to-dos are the "Forms ready"
meter (tests/test_build25_score.py). Every test below that pinned the row or the
notice pinned the 14 Oct rule - the TESTS were updated, the code is the new rule.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
UTIL = ROOT / "frontend" / "src" / "utils" / "recommendations.js"
MODAL = ROOT / "frontend" / "src" / "components" / "form" / "AcordModal.jsx"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

# The live package's own numbers (read-only snapshot of f83757cf).
WEIGHTS = {"narrative_quality": 0.1, "property_integrity": 0.15, "exposure_consistency": 0.25,
           "loss_history_alignment": 0.15, "structural_completeness": 0.25, "umbrella_limit_adequacy": 0.1}
PILLARS = {"narrative_quality": 100, "property_integrity": 100, "exposure_consistency": 100,
           "loss_history_alignment": None, "structural_completeness": 98, "umbrella_limit_adequacy": 100}
FILL_ROW = {"field": None, "score": 98, "pillar": "structural_completeness", "missing": [],
            "action": "Confirm the Please verify values on each form (Form Fill Rate 93%)",
            "answer_mode": "none", "closes_with": "review", "points_available": 0.6}


def _pkg(fill=93, rows=None, score=99):
    return {
        "package_sqs_score": score, "without_forms": {"score": 100},
        "weights_used": WEIGHTS, "pillars": PILLARS,
        "category_breakdown": {"structural_completeness": {
            "fill": {"label": "Form Fill Rate", "score": fill, "weight": 0.25},
            "tier1": {"score": 100, "weight": 0.4}, "tier2": {"score": 100, "weight": 0.35}}},
        "top_recommendations": [FILL_ROW] if rows is None else rows,
    }


def _rows(n, status="verify"):
    return [{"field": f"F{i}", "status": status, "label": f"Box {i}"} for i in range(n)]


ATTENTION = {"forms": [
    {"form_id": "ACORD_125", "form_label": "ACORD 125", "rows": _rows(6)},
    {"form_id": "ACORD_28", "form_label": "ACORD 28", "rows": _rows(22)},
    {"form_id": "ACORD_131__excess", "form_label": "ACORD 131 (Excess)", "rows": _rows(1)},
    {"form_id": "ACORD_101", "form_label": "ACORD 101", "rows": _rows(2, "missing")},
]}


def _run(tmp_path, body):
    script = tmp_path / "check.mjs"
    script.write_text(f"import * as R from {json.dumps(UTIL.as_uri())};\n{body}\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _build(tmp_path, pkg, attention, forms_exist=True):
    return _run(tmp_path, (
        f"const m = R.buildRecommendations({{ packageSqs: {json.dumps(pkg)}, groupedIssues: null, "
        f"keyDetails: null, attention: {json.dumps(attention)}, formsExist: {json.dumps(forms_exist)} }});\n"
        "console.log(JSON.stringify({ score: m.score, consider: R.considerText(m) }));"))


@needs_node
def test_the_live_99_lists_its_last_point(tmp_path):
    # 23 Oct 2026: no fill-rate row, after forms or before; the two Missing boxes on
    # ACORD 101 still stay in "your forms need".
    o = _build(tmp_path, _pkg(), ATTENTION)
    assert not [s for s in o["score"] if s["id"] == "score:fill"]
    assert o["consider"] == "2 your forms need"


@needs_node
def test_not_listed_before_forms_or_at_a_full_fill_rate(tmp_path):
    assert not [s for s in _build(tmp_path, _pkg(), ATTENTION, forms_exist=False)["score"]
                if s["id"] == "score:fill"]
    assert not [s for s in _build(tmp_path, _pkg(fill=100), ATTENTION)["score"] if s["id"] == "score:fill"]


@needs_node
def test_not_listed_when_confirm_all_cannot_move_it(tmp_path):
    # no Please verify values (a fill rate held by, say, conflicted boxes) or the
    # list not loaded yet: no promise the row cannot keep
    no_verify = {"forms": [{"form_id": "ACORD_125", "form_label": "ACORD 125", "rows": _rows(3, "missing")}]}
    assert not [s for s in _build(tmp_path, _pkg(), no_verify)["score"] if s["id"] == "score:fill"]
    assert not [s for s in _build(tmp_path, _pkg(), None)["score"] if s["id"] == "score:fill"]


@needs_node
def test_a_tier_gap_row_and_the_fill_row_are_both_listed(tmp_path):
    # Tier 1 incomplete: the scorer's structural row asks for the box (a field) and
    # is listed; a fill rate below 100 adds no row any more (23 Oct 2026).
    tier_row = dict(FILL_ROW, field="mailing_address", answer_mode="field",
                    action="Applicant mailing address", points_available=3.2)
    o = _build(tmp_path, _pkg(fill=80, rows=[tier_row], score=95), ATTENTION)
    ids = [s["id"] for s in o["score"]]
    assert "score:fill" not in ids and ids
    # at 99 the list holds one point and the tier row takes it (never past 100)
    o = _build(tmp_path, _pkg(fill=80, rows=[tier_row], score=99), ATTENTION)
    pts = {s["id"]: s["points"] for s in o["score"]}
    assert "score:fill" not in pts and sum(p["points"] for p in pts.values()) == 1


@needs_node
def test_the_scorer_row_alone_is_still_not_a_fix_window(tmp_path):
    # the scorer's own row has no window, and no fill row stands in for it now
    o = _build(tmp_path, _pkg(), ATTENTION)
    assert [s["id"] for s in o["score"]] == []


def test_open_to_fix_opens_the_forms_not_a_window():
    src = MODAL.read_text(encoding="utf-8")
    start = src.index("const openScoreFix = (item) => {")
    body = src[start:src.index("};", start)]
    assert 'item.resolution.mode === "forms"' in body
    assert "openFormAtBox(item.resolution.form_id" in body
    # the forms branch returns before the fix window is set (through the deep-link
    # door since 23 Oct 2026, `openFixWindow`)
    assert body.index("openFormAtBox(") < body.index("openFixWindow(")


# ── The Overview notice (owner, 14 Oct 2026): "your last points are on the forms" ──

RAIL = ROOT / "frontend" / "src" / "components" / "form" / "review" / "ReviewRailLayout.jsx"


def test_the_overview_notice_is_gone_and_the_meter_is_in_its_place(tmp_path):
    """The 14 Oct notice ("Everything on this review is done. Your last points are
    on the forms.") promised points the forms no longer hold (23 Oct 2026)."""
    if shutil.which("node") is not None:
        o = _run(tmp_path, "console.log(JSON.stringify({ left: typeof R.scoreLeftOnForms, fill: typeof R.fillRateItem }));")
        assert o == {"left": "undefined", "fill": "undefined"}
    src = RAIL.read_text(encoding="utf-8")
    assert 'data-testid="overview-forms-left"' not in src and "scoreLeftOnForms" not in src
    assert 'data-forms-ready="review"' in src
    css = (ROOT / "frontend" / "src" / "components" / "form" / "review" / "ReviewRailLayout.css").read_text(encoding="utf-8")
    assert ".rr-forms-left {" not in css
