"""Save progress (owner, 13 Oct 2026) - a fix that is not finished is not Resolved.

The owner's run `18f6914f`: the COPE hard stop's window (location table + occupancy type above
it) was saved with the table filled and occupancy type blank. The screen marked it Resolved -
green tag, "Reopen", "All 1 handled" - while the stop still fired ("missing: occupancy type")
and still held the score. The status was set on every successful save, whatever the save did.

Owner: "unless a hard stop is completely fixed ... we should not put it in resolved section and
also we should not put a resolved tag ... just leave it there and don't enable apply the fix
button but instead add a save progress button ... Do this for all hard stops / warnings that
have more than one field or rows or expect multiple values."

Now:
  * whether a save fixed the item is read off the issue lists the server sends back
    (`utils/fixProgress.fixLeftOpen`) - the same item still listed, or its rule firing under
    NEW words (a partly fixed card renames what is missing), means it is still open;
  * an unfinished item keeps "Open to fix", gets no tag, and a stale "resolved" from an earlier
    partial save is taken off;
  * a table window that still lacks a value it shows says what is missing and its button reads
    "Save progress"; it saves and closes, and opening it again shows what was saved.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"
_MODAL = _FRONT / "components" / "form" / "AcordModal.jsx"
_WINDOW = _FRONT / "components" / "form" / "ResolutionModal.jsx"


def _node(tmp_path, body):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / "check.mjs"
    script.write_text(f"import * as P from {json.dumps((_FRONT / 'utils' / 'fixProgress.js').as_uri())};\n"
                      + body + "\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


# The live shape of 18f6914f's review response: grouped hard stops, warnings by tier.
_COPE = {"issue_id": "iss_57ef2c1bec59", "code": "legacy_minimum_viable_cope", "forms": [],
         "message": "Property Minimum Viable COPE incomplete - missing: occupancy type "
                    "Fix: Review and correct this before proceeding."}
_GL = {"issue_id": "iss_gl", "code": "legacy_gl_no_exposure_basis", "forms": [],
       "message": "GL exposure basis missing"}


def _grouped(hard, warn=()):
    return {"hard_stops": [{"title": "Property COPE completeness", "count": len(hard), "items": list(hard)}] if hard else [],
            "warnings": {"required": [{"count": len(warn), "items": list(warn)}] if warn else [],
                         "recommended": [], "binder_followup": []}}


_ID = "const idOf = (i) => (i && i.issue_id) || ('f_' + String(i && i.message));"


def test_a_save_that_leaves_the_stop_firing_is_not_resolved(tmp_path):
    out = _node(tmp_path, f"""{_ID}
const before = P.listedIssues({{ grouped: {json.dumps(_grouped([_COPE], [_GL]))} }});
const sameAfter = P.listedIssues({{ grouped: {json.dumps(_grouped([_COPE], [_GL]))} }});
const fixedAfter = P.listedIssues({{ grouped: {json.dumps(_grouped([], [_GL]))} }});
const issue = {json.dumps(_COPE)};
console.log(JSON.stringify({{
  live: P.fixLeftOpen(issue, before, sameAfter, idOf),
  fixed: P.fixLeftOpen(issue, before, fixedAfter, idOf),
  counted: before.length,
}}));
""")
    # 18f6914f: table saved, occupancy blank -> the same stop comes back -> NOT resolved
    assert out["live"] is True
    # occupancy entered -> the stop is gone -> resolved
    assert out["fixed"] is False
    assert out["counted"] == 2


def test_a_partly_fixed_card_that_renames_what_is_missing_stays_open(tmp_path):
    before_cope = dict(_COPE, issue_id="iss_old",
                       message="Property Minimum Viable COPE incomplete - missing: occupancy type, construction type")
    after_cope = dict(_COPE, issue_id="iss_new")       # "missing: occupancy type" - new words, new id
    other_loc = {"issue_id": "iss_loc2", "code": "per_location_cope_incomplete", "message": "Location 2 lacks COPE"}
    loc1 = {"issue_id": "iss_loc1", "code": "per_location_cope_incomplete", "message": "Location 1 lacks COPE"}
    out = _node(tmp_path, f"""{_ID}
const renamed = P.fixLeftOpen({json.dumps(before_cope)},
  P.listedIssues({{ grouped: {json.dumps(_grouped([before_cope]))} }}),
  P.listedIssues({{ grouped: {json.dumps(_grouped([after_cope]))} }}), idOf);
// location 1 fixed in full; location 2's own item was there before and stays: a DIFFERENT item
const otherItem = P.fixLeftOpen({json.dumps(loc1)},
  P.listedIssues({{ cross: {json.dumps([loc1, other_loc])} }}),
  P.listedIssues({{ cross: {json.dumps([other_loc])} }}), idOf);
// no code -> only the same item counts
const bare = P.fixLeftOpen({{ message: 'Plain sentence' }},
  P.listedIssues({{ hardStops: ['Plain sentence'] }}),
  P.listedIssues({{ hardStops: ['Another sentence'] }}), idOf);
const bareLive = P.fixLeftOpen({{ message: 'Plain sentence' }},
  P.listedIssues({{ hardStops: ['Plain sentence'] }}),
  P.listedIssues({{ hardStops: ['Plain sentence'] }}), idOf);
console.log(JSON.stringify({{ renamed, otherItem, bare, bareLive }}));
""")
    assert out == {"renamed": True, "otherItem": False, "bare": False, "bareLive": True}


def test_the_same_item_is_found_whichever_list_carries_it(tmp_path):
    """The editor's panel reads raw cross-form issues (no server id) while the review reads the
    grouped view (server id): the same words are the same item, so neither can mark a live stop
    Resolved by looking in the other list."""
    raw = {"code": "umbrella_gl_period_misaligned", "message": "Umbrella and GL periods differ", "forms": ["ACORD_131"]}
    grouped_item = dict(raw, issue_id="iss_server_sha")
    out = _node(tmp_path, f"""{_ID}
const issue = {json.dumps(grouped_item)};
const before = P.listedIssues({{ cross: {json.dumps([raw])} }});
const after = P.listedIssues({{ cross: {json.dumps([raw])} }});
const singleCluster = P.listedIssues({{ grouped: {{ hard_stops: [{{ issue_id: 'iss_c', primary_message: 'One stop', forms: [], code: 'x' }}] }} }});
console.log(JSON.stringify({{ live: P.fixLeftOpen(issue, before, after, idOf),
  cluster: singleCluster.map((i) => i.message + '|' + i.code), empty: P.listedIssues({{}}).length,
  noLists: P.fixLeftOpen(issue, before, [], idOf) }}));
""")
    assert out["live"] is True
    assert out["cluster"] == ["One stop|x"]
    assert out["empty"] == 0
    # a reply with no lists at all cannot prove the item still fires
    assert out["noLists"] is False


def test_what_a_window_still_misses(tmp_path):
    out = _node(tmp_path, """
console.log(JSON.stringify([
  P.stillMissing({ boxes: [['Occupancy Type', '']], hasTable: true, table: '' }),
  P.stillMissing({ boxes: [['Occupancy Type', 'Office']], hasTable: true, table: 'Street address on row 2' }),
  P.stillMissing({ boxes: [['Occupancy Type', '']], hasTable: true, table: 'Street address on rows 1 and 2' }),
  P.stillMissing({ boxes: [['Occupancy Type', 'Office']], hasTable: true, table: '' }),
  P.stillMissing({ boxes: [], hasTable: true, table: '' }),
  P.stillMissing({ boxes: [['Revenue', '']], hasTable: false }),
  P.stillMissing({ boxes: [['Revenue', ''], ['Payroll', '5']], hasTable: false }),
  P.stillMissing({}),
]));
""")
    assert out == [
        "Occupancy Type",                                        # the 18f6914f window
        "Street address on row 2",
        "Occupancy Type; Street address on rows 1 and 2",
        "",                                                      # complete -> Apply
        "",
        "",                                                      # one box: no partial state
        "Revenue",
        "",
    ]


def test_the_status_is_set_only_when_the_save_fixed_it():
    src = _MODAL.read_text(encoding="utf-8")
    i = src.index("const handleIssueResolved = (data, issue) =>")
    body = src[i:src.index("const handleReopenIssue = async", i)]
    tail = body[body.index("const before = listedIssues("):]
    # the lists on screen before the save, against the lists the server just sent
    assert "listedIssues({ grouped: groupedIssues, cross: crossIssues, hardStops, softStops })" in tail
    assert "listedIssues({ grouped: data.grouped_issues, cross: data.cross_issues" in tail
    # still firing -> no "resolved"; a stale one is taken off; only then "resolved"
    left = tail.index("fixLeftOpen(issue, before, after, issueIdOf)")
    reset = tail.index('setIssueStatus(iid, "open", meta)')
    mark = tail.index('setIssueStatus(iid, "resolved", meta)')
    assert left < reset < mark
    assert 'issueStatuses.get(iid)?.status === "resolved"' in tail
    # the unconditional mark that caused 18f6914f is gone
    assert 'if (iid) setIssueStatus(iid, "resolved", { form_id:' not in body


def test_the_window_says_save_progress_while_a_value_is_missing():
    src = _WINDOW.read_text(encoding="utf-8")
    # 13 Oct 2026: the import also brings the narrative options' coverage readers
    # (tests/test_recommendations_resolved_13oct.py) - the pin follows it.
    assert "import { stillMissing as windowStillMissing, unmetNeeds, rowNeedsSummary, unfinishedStarters, textForCoverage, gapCovered } from '../../utils/fixProgress';" in src
    i = src.index("const progressGap =")
    calc = src[i:src.index("const label = {", i)]
    # a table window, the boxes above it, and the table's own required cells
    assert "mode === 'schedule' && schedule && !loading && !prefillLoading" in calc
    assert "boxes: extraFacts.map((f) => [humanizeFact(f), values[f]])" in calc
    assert "hasTable: true" in calc
    # the button and the line above it
    # Later the same night the label checks the gap for BOTH window kinds (a
    # box window's declared `needs` too - test_fixes_before_generation_13oct).
    assert "progressGap\n                      ? 'Save progress'" in src
    assert "progressGap ? 'Saving...' : 'Applying...'" in src
    assert "{progressGap && !note && (" in src
    assert "Save your progress now and finish it later - it stays open until everything is in." in src
    # no em-dash in the new words
    assert "—" not in src[src.index("{progressGap && !note && ("):src.index("{progressGap && !note && (") + 600]
