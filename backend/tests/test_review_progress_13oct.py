"""The review page's "x of y handled" (owner, 13 Oct 2026).

Owner, on run 841bb967: every hard stop and warning fixed, and the page read "0 of 0 items
handled"; with one hard stop left it read "0 of 1". A fixed item stops firing and leaves its
list, and the count read only what was still listed. Owner: "it should show x of y handled -
y were all the blockers initially and x is how many are handled - and if 0 remaining then
remove this."

Now:
  * y = the items still listed + the page's Resolved rows (dismissed, and fixed items that
    stopped firing, rebuilt from their stored status); x = the Resolved rows
    (`resolvedIssues.pageProgress`);
  * a save that clears OTHER listed blockers - a key-detail link, a "Raise your score" row, or
    another card's fix - records them "resolved" (`resolvedIssues.clearedBlockers`, with the
    Save progress rule `fixLeftOpen`), so they count and move to the Resolved section;
  * nothing left: no "x of y" at all.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"
_RAIL = _FRONT / "components" / "form" / "review" / "ReviewRailLayout.jsx"
_MODAL = _FRONT / "components" / "form" / "AcordModal.jsx"


def _node(tmp_path, body):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / "check.mjs"
    script.write_text(
        f"import * as R from {json.dumps((_FRONT / 'utils' / 'resolvedIssues.js').as_uri())};\n"
        f"import * as F from {json.dumps((_FRONT / 'utils' / 'fixProgress.js').as_uri())};\n"
        "const idOf = (i) => i.issue_id || ('m:' + i.message);\n" + body + "\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_y_counts_the_handled_blockers_too(tmp_path):
    out = _node(tmp_path, """
const open = [{count: 1, items: [{issue_id: "h1", message: "COPE"}]}];
const resolved = [{iid: "w1"}, {iid: "w2"}, {iid: "w3"}, {iid: "w4"}, {iid: "w5"}];
console.log(JSON.stringify({
  oneLeft: R.pageProgress(open, resolved),
  allDone: R.pageProgress([], resolved),
  never: R.pageProgress([], []),
  singleCluster: R.pageProgress([{issue_id: "x", primary_message: "m"}], []),
}));""")
    assert out["oneLeft"] == {"open": 1, "done": 5, "total": 6}       # was "0 of 1"
    assert out["allDone"] == {"open": 0, "done": 5, "total": 5}       # was "0 of 0"
    assert out["never"] == {"open": 0, "done": 0, "total": 0}
    assert out["singleCluster"]["open"] == 1


def test_a_save_that_clears_other_blockers_records_them(tmp_path):
    out = _node(tmp_path, """
const before = {hard_stops: [{cluster: "cope", items: [{issue_id: "h1", code: "legacy_minimum_viable_cope", message: "COPE missing: occupancy type"}]}],
  warnings: {required: [{cluster: "tier1", items: [{issue_id: "w1", code: "tier1_missing_Applicant mailing address", message: "mailing address missing"},
                                                {issue_id: "w2", code: "tier1_missing_Contact information", message: "contact missing"}]}],
             recommended: [], binder_followup: []}};
// The mailing address was typed through the key-details link: w1 is gone.
const after = {hard_stops: before.hard_stops, warnings: {required: [{cluster: "tier1", items: [before.warnings.required[0].items[1]]}], recommended: [], binder_followup: []}};
const cleared = R.clearedBlockers(before, after, idOf, F.fixLeftOpen);
// The COPE window saved part of it: same code, NEW words - not cleared.
const after2 = {hard_stops: [{cluster: "cope", items: [{issue_id: "h2", code: "legacy_minimum_viable_cope", message: "COPE missing: construction type"}]}],
  warnings: before.warnings};
const partial = R.clearedBlockers(before, after2, idOf, F.fixLeftOpen);
const own = R.clearedBlockers(before, after, idOf, F.fixLeftOpen, new Set(["w1"]));
const noView = R.clearedBlockers(before, undefined, idOf, F.fixLeftOpen);
console.log(JSON.stringify({cleared: cleared.map((c) => [c.iid, c.page]), partial: partial.length,
  own: own.length, noView: noView.length}));""")
    assert out["cleared"] == [["w1", "warning"]]
    assert out["partial"] == 0        # a part-fixed item is never marked
    assert out["own"] == 0            # the save's own item: its window's rule decides
    assert out["noView"] == 0         # no new view sent: nothing is known


def test_the_rail_counts_resolved_rows_and_hides_the_count_when_done():
    src = _RAIL.read_text(encoding="utf-8")
    assert "pageProgress(hardSplit.open, hardResolved)" in src
    assert "const totalItems = docsOpen + conflictsOpen + confirmedCount + hardProg.total + warnProg.total;" in src
    assert "const handledItems = confirmedCount + hardProg.done + warnProg.done;" in src
    # Nothing left: no "x of y" on the Overview panel or the rail.
    assert "{openItems > 0 && (" in src and 'data-testid="overview-progress"' in src
    assert 'sub: openItems > 0 ? `${handledItems} of ${totalItems} handled` : totalItems > 0 ? "All handled" : "Nothing to handle"' in src
    assert "—" not in src


def test_every_fix_route_records_what_it_cleared():
    src = _MODAL.read_text(encoding="utf-8")
    start = src.index("const handleIssueResolved = (data, issue) => {")
    body = src[start:start + 600]
    # Recorded BEFORE the early returns for key details, score rows and dry-run items.
    assert body.index("markClearedBlockers(data, issue);") < body.index("__scoreItem")
    assert "clearedBlockers(groupedIssues, data?.grouped_issues, issueIdOf, fixLeftOpen" in src
