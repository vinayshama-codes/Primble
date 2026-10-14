"""The last points after forms are listed (14 Oct 2026, live run f83757cf).

The owner: "package score is 99/100 now and I can't see any warning or anything to
make it 100". The 99 was the Form Fill Rate slice (93%): 57 AI values on eight forms
nobody had confirmed (0.85 / 0.50 against a confirmed 1.00). The scorer said so in a
row with no fix window, and the Recommendations section lists only rows it can open,
so the page showed nothing. The row is now listed after forms - only while the forms'
needs-attention lists hold Please verify values, the one thing "Confirm all" can fix -
and "Open to fix" opens the form with the most of them.
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


def _pkg(fill=93, rows=None):
    return {
        "package_sqs_score": 99, "without_forms": {"score": 100},
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
    o = _build(tmp_path, _pkg(), ATTENTION)
    fill = [s for s in o["score"] if s["id"] == "score:fill"]
    assert len(fill) == 1
    row = fill[0]
    assert row["title"] and "Form Fill Rate 93%" in row["detail"] and "3 forms" in row["detail"]
    assert '"Confirm all"' in row["detail"]
    # the form with the most Please verify values opens first; Missing-only forms are not counted
    assert row["resolution"] == {"mode": "forms", "form_id": "ACORD_28",
                                 "forms": ["ACORD_28", "ACORD_125", "ACORD_131__excess"]}
    assert row["points"] == {"points": 1, "exact": False}
    # the two Missing boxes on ACORD 101 stay in "your forms need"
    assert o["consider"] == "1 to raise your score \u00b7 2 your forms need"
    assert "—" not in row["detail"]


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
    # Tier 1 incomplete: the scorer's structural row asks for the box (a field),
    # and the fill slice's points come from its own bound
    tier_row = dict(FILL_ROW, field="mailing_address", answer_mode="field",
                    action="Applicant mailing address", points_available=3.2)
    o = _build(tmp_path, _pkg(fill=80, rows=[tier_row]), ATTENTION)
    ids = [s["id"] for s in o["score"]]
    assert "score:fill" in ids and any(i != "score:fill" for i in ids)
    fill = [s for s in o["score"] if s["id"] == "score:fill"][0]
    # (100 - 80) x 0.25 x 0.25 / 0.85 = 1.47 -> "up to +1 pts"
    assert fill["points"] == {"points": 1, "exact": False}


@needs_node
def test_the_scorer_row_alone_is_still_not_a_fix_window(tmp_path):
    # the scorer's own row has no window; only the fill row lists it (no twin)
    o = _build(tmp_path, _pkg(), ATTENTION)
    assert [s["id"] for s in o["score"]] == ["score:fill"]


def test_open_to_fix_opens_the_forms_not_a_window():
    src = MODAL.read_text(encoding="utf-8")
    start = src.index("const openScoreFix = (item) => {")
    body = src[start:src.index("};", start)]
    assert 'item.resolution.mode === "forms"' in body
    assert "openFormAtBox(item.resolution.form_id" in body
    # the forms branch returns before the fix window is set
    assert body.index("openFormAtBox(") < body.index("setResolutionIssue(")


# ── The Overview notice (owner, 14 Oct 2026): "your last points are on the forms" ──

RAIL = ROOT / "frontend" / "src" / "components" / "form" / "review" / "ReviewRailLayout.jsx"


def _left(tmp_path, pkg, attention, open_on_page=0):
    return _run(tmp_path, (
        f"const pkg = {json.dumps(pkg)};\n"
        f"const m = R.buildRecommendations({{ packageSqs: pkg, groupedIssues: null, keyDetails: null, "
        f"attention: {json.dumps(attention)}, formsExist: true }});\n"
        f"const l = R.scoreLeftOnForms({{ packageSqs: pkg, model: m, openOnPage: {open_on_page} }});\n"
        "console.log(JSON.stringify(l ? { score: l.score, formId: l.formId, formCount: l.formCount, "
        "reaches100: l.reaches100, points: l.points } : null));"))


@needs_node
def test_the_notice_shows_when_only_the_forms_are_left(tmp_path):
    o = _left(tmp_path, _pkg(), ATTENTION)
    assert o == {"score": 99, "formId": "ACORD_28", "formCount": 3, "reaches100": True,
                 "points": {"points": 1, "exact": False}}


@needs_node
def test_the_notice_stays_away_while_the_page_can_still_raise_the_score(tmp_path):
    # something still open on the review page
    assert _left(tmp_path, _pkg(), ATTENTION, open_on_page=1) is None
    # a capped score: its hard stops / warnings are the fix
    assert _left(tmp_path, dict(_pkg(), cap_applied=85, cap_reason="warning"), ATTENTION) is None
    # a "Raise your score" row the page can fix itself
    typed = dict(FILL_ROW, field="mailing_address", answer_mode="field",
                 action="Applicant mailing address", points_available=3.2)
    assert _left(tmp_path, _pkg(rows=[typed]), ATTENTION) is None
    # nothing on the forms to confirm, or a full score
    no_verify = {"forms": [{"form_id": "ACORD_125", "form_label": "ACORD 125", "rows": _rows(3, "missing")}]}
    assert _left(tmp_path, _pkg(), no_verify) is None
    assert _left(tmp_path, dict(_pkg(), package_sqs_score=100), ATTENTION) is None


@needs_node
def test_the_notice_never_promises_100_when_more_than_the_forms_is_missing(tmp_path):
    o = _left(tmp_path, dict(_pkg(), without_forms={"score": 96}), ATTENTION)
    assert o and o["reaches100"] is False


def test_the_overview_renders_it_in_neutral_words():
    src = RAIL.read_text(encoding="utf-8")
    assert 'data-testid="overview-forms-left"' in src
    assert "scoreLeftOnForms({ packageSqs, model: recModel" in src
    # everything the page still lists keeps it away
    assert "openOnPage: docsOpen + conflictsOpen + hardOpen + warnOpen" in src
    block = src[src.index('data-testid="overview-forms-left"'):]
    block = block[:block.index("</div>\n        )}")]
    assert "rr-note--amber" not in block and "—" not in block
    css = (ROOT / "frontend" / "src" / "components" / "form" / "review" / "ReviewRailLayout.css").read_text(encoding="utf-8")
    assert ".rr-forms-left {" in css and "#f8fafc" in css
