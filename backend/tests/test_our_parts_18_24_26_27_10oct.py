"""Our parts of Brent's Choice Electric items 18, 24, 26 and 27 (owner, 10 Oct 2026).

18 - The fix window answered Apply with "Enter at least one value." while it SHOWED the
     values on file: it sent only boxes the producer typed in. With nothing typed, Apply
     now confirms what the window shows ("Confirm this value"); typing keeps the old rule
     (only typed boxes go). `frontend/src/utils/fixWindow.js`.
24 - Form names on the editor's Cross-Form rows and the fix window were pink PILLS; they
     are plain pink text.
26 - Exposure looked wrong: each row printed 100 minus its OWN deduction ("80%") while
     the pillar is 100 minus ALL of them, and two rows named the wrong cause - "Operations"
     carried "no GL class codes", "Cross-Document Consistency" carried two cross-form hard
     stops (Minimum Viable COPE, Period of Restoration) on documents that agreed. Rows now
     print "-N pts" and are named by what they charge. Display only: no score moves.
27 - The download review's headline added every row of every kind ("176 items flagged";
     190 on the owner's run `2076fe35`). It counts what there is to FIX - hard stops and
     the producer's Missing boxes, 47 on that run - and names the rest; the checklist
     after the download lists its hard stops first, not after every form's rows.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from services import sqs_service as sq

_BACKEND = Path(__file__).resolve().parents[1]
_FRONT = _BACKEND.parent / "frontend" / "src"
_MODAL = _FRONT / "components" / "form" / "AcordModal.jsx"
_FIX = _FRONT / "components" / "form" / "ResolutionModal.jsx"
_PANEL = _FRONT / "components" / "form" / "NeedsAttentionPanel.jsx"
_FIX_JS = _FRONT / "utils" / "fixWindow.js"
_ATTN_JS = _FRONT / "utils" / "needsAttention.js"
_FMT_JS = _FRONT / "utils" / "formatters.js"


def _node(tmp_path, imports, body):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / "check.mjs"
    script.write_text("".join(f"import * as {name} from {json.dumps(path.as_uri())};\n"
                              for name, path in imports.items()) + body + "\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _src(path):
    return path.read_text(encoding="utf-8")


def _attention_module(tmp_path):
    """needsAttention.js without its network import (`import.meta.env` is Vite's)."""
    body = re.sub(r'^import \{ API_BASE \} from "\.\./config/constants";\n', 'const API_BASE = "";\n',
                  _src(_ATTN_JS), flags=re.M)
    path = tmp_path / "na.mjs"
    path.write_text(body, encoding="utf-8")
    return path


# ══ 26. Exposure rows: named by what they charge, printed as points ═══════════
def test_the_two_rows_are_named_by_what_they_charge():
    assert sq.EXPOSURE_BUCKET_LABELS["operations_description"] == "Class Codes & Operations"
    assert sq.EXPOSURE_BUCKET_LABELS["cross_document_consistency"] == "Cross-Form Checks"
    # the keys stay - stored payloads, the C3 trace and the tests key on them
    # (19 Oct 2026, Brent: missing details are Completeness) plus its own cross-form bucket.
    assert set(sq.EXPOSURE_BUCKET_LABELS) == {
        "operations_description", "coverage_information", "payroll_employee_information",
        "revenue_sales_information", "cross_document_consistency", "auto_completeness",
        "wc_supplemental", "cross_form_details"}
    assert sq.EXPOSURE_BUCKET_LABELS["cross_form_details"] == "Cross-Form Details"


def _brents_package():
    """The owner's run `2076fe35`: GL with no class codes, and the two cross-form hard
    stops no document can clear - nothing else charged. They reach the scorer as the
    pipeline hands them over: warnings, one status since 14 Oct (`cross_form_severity`)."""
    from services.stops_now import cross_form_severity
    facts = {"gl_limits": "$1,000,000 / $2,000,000"}
    flags = {"has_general_liability": True}
    hard = [{"type": "hard_stop", "code": "minimum_viable_cope_missing", "message": "COPE"},
            {"type": "hard_stop", "code": "bi_missing_period_of_restoration", "message": "PoR"}]
    return facts, flags, cross_form_severity(hard)


def test_brents_package_charges_class_codes_and_cross_form_checks_under_their_own_names():
    facts, flags, warn = _brents_package()
    # (19 Oct 2026, Brent: Exposure = conflicts only) neither charge is a conflict...
    score, subs = sq._calculate_exposure_consistency(facts, flags, [], warn)
    assert score == 100 and set(subs.values()) == {100}
    cats = sq._compute_category_breakdown({}, {}, exposure_subscores=subs)["exposure_consistency"]
    assert cats["operations_description"]["label"] == "Class Codes & Operations"
    assert cats["cross_document_consistency"]["label"] == "Cross-Form Checks"
    # the rows add up to the pillar: 100 minus every row's points
    assert 100 - sum(c["deducted"] for c in cats.values()) == score
    # ...so both are Completeness's Coverage Details, each under its own name: the class
    # codes' 20 and the two cross-form checks' 5 each.
    items = sq.completeness_deduction_items(facts, flags, [], warn)
    assert [(i["bucket"], i["points"], i["fact"]) for i in items] == [
        ("operations_description", 20, "gl_class_codes_by_location"),
        ("cross_form_details", 10, None)]
    assert [sq.exposure_bucket_label(i["bucket"]) for i in items] == [
        "Class Codes & Operations", "Cross-Form Details"]


def test_the_unscored_fallback_reads_the_same_label_table():
    cats = sq._compute_category_breakdown({}, {"has_general_liability": True})["exposure_consistency"]
    for key, cat in cats.items():
        assert cat["label"] == sq.exposure_bucket_label(key)
    body = _src(Path(sq.__file__))
    assert '"Cross-Document Consistency"),' not in body and '"Operations"),' not in body


def _stored_payload():
    return {
        "package_sqs_score": 41,
        "category_breakdown": {
            "exposure_consistency": {
                "operations_description": {"label": "Operations", "score": 80, "deducted": 20},
                "cross_document_consistency": {"label": "Cross-Document Consistency", "score": 80,
                                               "deducted": 20},
                "auto_completeness": {"label": "Auto Completeness", "score": 85, "deducted": 15},
            },
            "loss_history_alignment": {"loss_history": {"label": "Loss History", "score": 25}},
        },
        "top_recommendations": [
            {"pillar": "exposure_consistency",
             "action": "Incomplete: Operations, Cross-Document Consistency, Auto Completeness"},
            {"pillar": "narrative_quality", "action": "Incomplete: Operations"},
        ],
    }


def test_a_stored_run_reads_todays_names_without_a_recalculation():
    stored = _stored_payload()
    kept = copy.deepcopy(stored)
    out = sq.with_current_bucket_labels(stored)
    assert stored == kept                                    # the caller's dict is untouched
    exp = out["category_breakdown"]["exposure_consistency"]
    assert exp["operations_description"]["label"] == "Class Codes & Operations"
    assert exp["cross_document_consistency"]["label"] == "Cross-Form Checks"
    assert exp["operations_description"]["deducted"] == 20 and out["package_sqs_score"] == 41
    assert out["top_recommendations"][0]["action"] == (
        "Incomplete: Class Codes & Operations, Cross-Form Checks, Auto Completeness")
    # only the Exposure pillar's action is about these buckets
    assert out["top_recommendations"][1]["action"] == "Incomplete: Operations"


def test_a_current_payload_comes_back_as_it_is():
    fresh = sq.with_current_bucket_labels(_stored_payload())
    assert sq.with_current_bucket_labels(fresh) is fresh
    for empty in (None, {}, {"pillars": {}}):
        assert sq.with_current_bucket_labels(empty) == empty


def test_every_renamed_label_points_at_a_bucket_and_is_no_longer_in_use():
    for old, key in sq._RENAMED_EXPOSURE_LABELS.items():
        assert key in sq.EXPOSURE_BUCKET_LABELS
        assert old not in sq.EXPOSURE_BUCKET_LABELS.values()


def test_both_doors_to_a_stored_score_rename():
    session = {"generated_forms": {"ACORD_125": {}}, "package_sqs": _stored_payload()}
    out = sq.current_package_sqs(session)
    assert out["category_breakdown"]["exposure_consistency"]["operations_description"]["label"] \
        == "Class Codes & Operations"
    routes = _src(_BACKEND / "routes" / "form_routes.py")
    assert re.search(r'"package_sqs": with_current_bucket_labels\(\s*proc_session\.get\("package_sqs"\)\)',
                     routes)


def test_a_deduction_row_prints_its_points(tmp_path):
    out = _node(tmp_path, {"F": _FMT_JS}, """
const cases = [20, 0, 3, 15, "12", -4, undefined, null, 7.6];
console.log(JSON.stringify(cases.map((n) => [F.deductionText(n), F.deductionColor(n)])));
""")
    green, amber, red = "#10b981", "#f59e0b", "#ef4444"
    assert out == [["-20 pts", red], ["0 pts", green], ["-3 pts", amber], ["-15 pts", red],
                   ["-12 pts", red], ["0 pts", green], ["0 pts", green], ["0 pts", green],
                   ["-8 pts", amber]]


def test_the_panel_prints_points_on_a_deduction_row():
    body = _src(_MODAL)
    i = body.index("const deducted = typeof cv?.deducted")
    row = body[i:i + 3000]
    assert "deductionText(deducted)" in row and "deductionColor(deducted)" in row
    # a weighted row (Structural) keeps its percentage
    assert "{cv.score}%" in row


# ══ 18. The fix window: Apply confirms what it shows ══════════════════════════
def _apply(tmp_path, cases):
    return _node(tmp_path, {"W": _FIX_JS}, f"""
const cases = {json.dumps(cases)};
console.log(JSON.stringify(cases.map(([facts, values, touched, opts]) => ({{
  ...W.fieldsToApply(facts, values, new Set(touched), opts || undefined),
  label: W.applyLabel(facts, values, new Set(touched)),
}}))));
""")


def test_apply_with_nothing_typed_confirms_the_values_shown(tmp_path):
    one, two = _apply(tmp_path, [
        [["property_building_value"], {"property_building_value": " 421714 "}, []],
        [["occupancy_type", "construction_type"],
         {"occupancy_type": "Office", "construction_type": "Frame"}, []],
    ])
    assert one == {"send": [["property_building_value", "421714"]], "confirming": True,
                   "error": None, "label": "Confirm this value"}
    assert two["send"] == [["occupancy_type", "Office"], ["construction_type", "Frame"]]
    assert two["label"] == "Confirm these values"


def test_typing_sends_only_the_typed_box(tmp_path):
    (out,) = _apply(tmp_path, [
        [["occupancy_type", "construction_type"],
         {"occupancy_type": "Office", "construction_type": "Joisted Masonry"}, ["construction_type"]],
    ])
    assert out == {"send": [["construction_type", "Joisted Masonry"]], "confirming": False,
                   "error": None, "label": "Apply"}


def test_an_empty_window_still_asks_for_a_value(tmp_path):
    empty, cleared, after_note = _apply(tmp_path, [
        [["occupancy_type"], {"occupancy_type": ""}, []],
        # typed into a box and emptied it, beside one that shows a value
        [["occupancy_type", "construction_type"],
         {"occupancy_type": "", "construction_type": "Frame"}, ["occupancy_type"]],
        # the window applied once and asks for one more value: nothing is re-sent
        [["occupancy_type", "construction_type"],
         {"occupancy_type": "Office", "construction_type": ""}, [], {"allowConfirm": False}],
    ])
    assert empty["send"] == [] and empty["error"] == "Enter at least one value."
    assert empty["label"] == "Apply"
    assert cleared["send"] == [] and "keep what is on file" in cleared["error"]
    assert after_note["send"] == [] and after_note["error"] == "Enter at least one value."


def test_the_window_applies_through_the_one_rule():
    body = _src(_FIX)
    i = body.index("const applyField = async")
    apply = body[i:body.index("const applyNarrative", i)]
    assert "fieldsToApply(fieldFacts, values, touched.current" in apply
    assert "allowConfirm: !note" in apply
    assert "touched.current.has(k) && String(v" not in apply
    assert "applyLabel(fieldFacts, values, touched.current)" in body


# ══ 24. Form names are plain pink text ════════════════════════════════════════
def test_form_names_are_not_pills():
    modal = _src(_MODAL)
    i = modal.index('title="Cross-Form Validation"')
    rows = modal[i:i + 4000]
    assert 'iss.forms.map((f) => formLabel(f)).join(", ")' in rows
    assert "borderRadius: 10" not in rows[:rows.index("actionable ?")]
    fix = _src(_FIX)
    assert "issue.forms.map((f) => instanceFormLabel(f)).join(', ')" in fix
    # the pill's fill is gone from the FORM NAMES (the 13 Oct "Still missing" chips
    # use the same pink for a ticked option - not a form name)
    names = fix[fix.index("Plain pink text, no pill"):fix.index('aria-label="Close"')]
    assert "#fce7f3" not in names and "borderRadius" not in names.split("instanceFormLabel")[0][-400:]


# ══ 27. The download review counts what there is to fix ═══════════════════════
def _owners_run():
    """`2076fe35` as the review receives it: 2 hard stops, 6 required boxes blocking the
    download, 8 other cards; 39 Missing boxes, 16 applicant signatures, 93 held back by
    the AI, 26 to verify."""
    recs = ([{"recommendation_type": "hard_stop", "rec_id": f"rec_h{i}"} for i in range(2)]
            + [{"recommendation_type": "suggestion", "rec_id": f"fieldqa_hardblock_ACORD_140_{i}"}
               for i in range(6)]
            + [{"recommendation_type": "missing_field", "rec_id": f"rec_m{i}"} for i in range(8)])
    rows = ([{"status": "missing"}] * 39 + [{"status": "missing", "applicant_step": True}] * 16
            + [{"status": "ai_held_back"}] * 93 + [{"status": "verify"}] * 26)
    attention = {"forms": [{"form_id": "ACORD_125", "rows": rows[:100]},
                           {"form_id": "ACORD_140", "rows": rows[100:]}],
                 "counts": {"total": 174}, "document_suggestions": []}
    return recs, attention


def test_the_owners_run_counts_the_listed_fix_items_and_each_group(tmp_path):
    # 14 Oct 2026 (owner): the review LISTS one by one only the items to fix -
    # hard stops (the gate's boxes included), warnings, recommendation cards and
    # Missing boxes - and shows "Please verify", "AI held back" and the
    # applicant's steps as ONE line each with its own count. The headline counts
    # the listed fix-items. (10 Oct: hard stops + Missing, the rest on an "Also
    # listed" line - the TEST pinned that rule and is updated with it.)
    recs, attention = _owners_run()
    out = _node(tmp_path, {"A": _attention_module(tmp_path)}, f"""
const c = A.downloadReviewCounts({json.dumps(recs)}, {json.dumps(attention)});
const lines = ["verify", "applicant", "choices"].map(k => A.groupLineText(k, c[k]));
console.log(JSON.stringify({{ c, lines, head: A.downloadReviewHeadline(c) }}));
""")
    # 23 Oct 2026 (Brent: "Users only need to see relevant information. The
    # audit record is fine."): no "AI held back" group - the 93 stale rows of
    # that status are not drawn or counted (the server no longer sends any).
    assert out["c"] == {"hard": 8, "warnings": 0, "recommendations": 8, "missing": 39, "verify": 26,
                        "applicant": 16, "choices": 0, "toFix": 55, "total": 97}
    assert out["head"] == "55 items to fix - review before downloading"
    assert out["lines"] == ["26 values to confirm", "16 boxes for the applicant to sign", ""]


def test_the_headline_for_nothing_to_fix_one_item_and_all_clear(tmp_path):
    out = _node(tmp_path, {"A": _attention_module(tmp_path)}, """
const only = A.downloadReviewCounts([], {forms: [{rows: [{status: "verify"}]}], document_suggestions: [{id: "s"}]});
const one = A.downloadReviewCounts([{recommendation_type: "hard_stop"}], null);
const none = A.downloadReviewCounts(null, undefined);
console.log(JSON.stringify([A.downloadReviewHeadline(only), A.groupLineText("verify", only.verify),
  A.groupLineText("choices", only.choices), A.downloadReviewHeadline(one), A.downloadReviewHeadline(none)]));
""")
    assert out == ["Nothing to fix - look over the groups below before downloading",
                   "1 value to confirm", "1 new-document choice",
                   "1 item to fix - review before downloading",
                   "All clear - review the SQS summary below"]


def test_both_download_screens_read_the_counts_and_list_hard_stops_first():
    body = _src(_MODAL)
    assert "items flagged - review before downloading" not in body
    assert "Unresolved items ({" not in body
    pre = body[body.index("function DownloadPreflightModal"):body.index("function DashboardAssistant")]
    assert "downloadReviewCounts(openRecs, attention)" in pre
    assert "downloadReviewHeadline(counts)" in pre and "Also listed" not in pre
    i = body.index("Post-download checklist")
    post = body[i:i + 4000]
    assert "downloadReviewCounts(recs, preflightAttention)" in post
    assert "To fix before sending (${counts.toFix})" in post
    # one list for both screens; hard stops first, the download gate's boxes
    # first among them (a required box blocking the download is a hard stop)
    assert body.count("<DownloadReviewList ") == 2
    panel = _src(_PANEL)
    fn = panel[panel.index("export function DownloadReviewList"):]
    assert fn.index('title="Hard Stops"') < fn.index('title="Warnings"') < fn.index("Missing on the forms") \
        < fn.index('title="Recommendations"') < fn.index("download-groups")
    util = _src(_ATTN_JS)
    assert 'includes("hardblock_")' in util


def test_the_forms_list_counts_each_kind_on_its_own():
    # 14 Oct 2026: each group is ONE line with its own count (`groupLineText`),
    # never one total over every kind.
    panel = _src(_PANEL)
    assert "Needs attention on the forms ({total})" not in panel
    assert "groupLineText(g.key, groupCount(g.key))" in panel
    assert "Missing on the forms ({missingCount})" in panel
