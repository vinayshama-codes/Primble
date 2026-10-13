"""The review screen's Resolved section and the end of "Resolve" there (owner, 8 Oct 2026).

Brent (Choice Electric test): fixed items must not vanish from Hard Stops / Warnings,
they tuck under a "Reviewed"-style section; and "Resolve" / "Dismiss" are only status
tags, so "Resolve" goes. The owner's spec: a hard stop or warning that is DISMISSED,
or fixed through "Open to fix", moves into a collapsed "Resolved (n)" section on its
page with a small "Resolved" / "Dismissed" label and "Open again" - the editor SQS
panel's "Reviewed" tuck, replicated. Each stored status now records its page
(`severity`), so a fixed item that stops firing is filed under the right page.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import services.audit_service as au
from models.schemas import IssueStatusRequest, SUBMISSION_ISSUE_STATUS_STATEMENTS

_FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"
_UTIL = _FRONT / "utils" / "resolvedIssues.js"
_RAIL = _FRONT / "components" / "form" / "review" / "ReviewRailLayout.jsx"
_MODAL = _FRONT / "components" / "form" / "AcordModal.jsx"


def _node(tmp_path, body):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / "check.mjs"
    script.write_text(
        f"import * as R from {json.dumps(_UTIL.as_uri())};\n"
        "const idOf = (it) => `${it.message}|${(it.forms || []).slice().sort().join(',')}`;\n"
        f"{body}\n",
        encoding="utf-8",
    )
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


# ── The helper's rules ────────────────────────────────────────────────────────
def test_a_dismissed_item_leaves_its_list_and_a_fixed_but_live_one_stays(tmp_path):
    out = _node(tmp_path, """
const clusters = [
  { cluster: "COPE", count: 3, forms: ["ACORD_140"], items: [
      { message: "Occupancy missing", forms: ["ACORD_140"] },
      { message: "Roof year missing", forms: ["ACORD_140"] },
      { message: "Sprinkler missing", forms: ["ACORD_140"] }] },
  { cluster: "Single", count: 1, issue_id: "x", primary_message: "Period of Restoration missing", forms: [] },
];
const st = { "Occupancy missing|ACORD_140": "dismissed", "Roof year missing|ACORD_140": "resolved",
             "Period of Restoration missing|": "dismissed" };
const r = R.splitClusters(clusters, { idOf, statusOf: (id) => st[id] });
console.log(JSON.stringify({
  open: r.open.map((c) => ({ count: c.count, items: (c.items || []).map((i) => i.message) })),
  handled: r.handled.map((h) => [h.item.message, h.status]),
}));
""")
    # Occupancy (dismissed) left; Roof year (resolved but still FIRING) stays - its
    # answer did not clear it; the single dismissed cluster is gone from the list.
    assert out["open"] == [{"count": 2, "items": ["Roof year missing", "Sprinkler missing"]}]
    assert out["handled"] == [["Occupancy missing", "dismissed"],
                              ["Period of Restoration missing", "dismissed"]]


def test_a_fixed_item_that_stopped_firing_is_rebuilt_on_its_own_page(tmp_path):
    out = _node(tmp_path, """
const entries = [
  ["a", { status: "resolved", message: "Mailing address missing", form_id: "ACORD_125", severity: "hard" }],
  ["b", { status: "dismissed", message: "Driver schedule not provided", severity: "warning" }],
  ["c", { status: "resolved", message: "Old row with no page" }],
  ["d", { status: "open", message: "Reopened", severity: "hard" }],
  ["e", { status: "resolved", message: null, severity: "hard" }],
  ["f", { status: "resolved", message: "Still listed", severity: "hard" }],
];
const live = new Set(["f"]);
console.log(JSON.stringify({
  hard: R.storedHandledRows(entries, { liveIds: live, page: "hard" }).map((r) => [r.iid, r.status, r.forms]),
  warn: R.storedHandledRows(entries, { liveIds: live, page: "warning" }).map((r) => r.iid),
}));
""")
    assert out["hard"] == [["a", "resolved", ["ACORD_125"]]]
    assert out["warn"] == ["b", "c"]          # an old status with no page files under Warnings


def test_each_row_once_and_open_again_by_kind(tmp_path):
    out = _node(tmp_path, """
const rows = R.resolvedRows([{ iid: "a", status: "dismissed" }], [{ iid: "a", status: "resolved" }, { iid: "b", status: "resolved" }]);
console.log(JSON.stringify({ ids: rows.map((r) => r.iid), kinds: rows.map(R.reopenKind),
                             settle: [R.reopenKind({ status: "dismissed", live: false }), R.reopenKind({ status: "dismissed", live: true }),
                                      R.reopenKind({ status: "resolved", live: false }), R.reopenKind(null)],
                             labels: R.RESOLVED_LABELS,
                             live: [...R.liveIdsOf([[{ count: 1, issue_id: "q", primary_message: "M", forms: [] }]], idOf)] }));
""")
    assert out["ids"] == ["a", "b"]
    assert out["kinds"] == ["status", "reopen"]     # dismissed -> back to its list; fixed -> reopen
    # A dismissed item that has STOPPED firing has nothing to reopen: no "Open
    # again" at all (9 Oct 2026 review - reopening it only made it vanish, and
    # relabelling it Resolved sent its next reopen down the fix path).
    assert out["settle"] == ["none", "status", "reopen", "reopen"]
    assert out["labels"] == {"resolved": "Resolved", "dismissed": "Dismissed"}
    assert out["live"] == ["M|"]


# ── The server stores and returns the page ───────────────────────────────────
def test_the_status_table_gains_its_page_column_on_startup():
    ddl = " ".join(SUBMISSION_ISSUE_STATUS_STATEMENTS)
    assert "severity      TEXT" in ddl
    assert "ALTER TABLE submission_issue_status ADD COLUMN IF NOT EXISTS severity TEXT" in ddl
    assert IssueStatusRequest(session_id="s", issue_id="i", status="resolved",
                              severity="hard").severity == "hard"


class _Conn:
    def __init__(self, sink):
        self.sink = sink

    async def execute(self, sql, *args):
        self.sink.append((sql, args))


class _Acquire:
    def __init__(self, sink):
        self.sink = sink

    async def __aenter__(self):
        return _Conn(self.sink)

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, sink):
        self.sink = sink

    def acquire(self):
        return _Acquire(self.sink)


@pytest.mark.parametrize("given,stored", [("hard", "hard"), ("warning", "warning"),
                                          ("Hard stop", None), (None, None)])
def test_the_page_is_written_and_never_guessed(monkeypatch, given, stored):
    sink: list = []
    monkeypatch.setattr(au, "get_pool", lambda: _Pool(sink))

    async def _no_event(*a, **k):
        return None
    monkeypatch.setattr(au, "record_material_change", _no_event, raising=False)
    ok = asyncio.run(au.set_issue_status("s1", "iss1", "resolved", message="M", severity=given))
    assert ok is True
    sql, args = sink[0]
    assert "severity=COALESCE(EXCLUDED.severity" in sql
    assert args[-1] == stored


def test_the_read_returns_the_page():
    src = Path(au.__file__).read_text(encoding="utf-8")
    sel = src[src.index("async def get_issue_statuses"):]
    assert "source_fact, message, updated_at, user_id, severity" in sel[:600]


# ── The review screen ────────────────────────────────────────────────────────
def test_the_review_screen_offers_no_resolve_and_the_editor_keeps_it():
    modal = _MODAL.read_text(encoding="utf-8")
    assert "function IssueStatusControl({ issueId, meta, status, onSet, showResolve = true })" in modal
    assert "showResolve={!ctx.reviewScreen}" in modal
    # Both review layouts pass the review context; the editor's calls do not.
    assert modal.count("{ reviewScreen: true, tone") == 3
    assert "renderItemActions={(it, forms, tone) => itemResolveAndStatus(it, forms, { reviewScreen: true, tone })}" in modal
    assert "onReopenIssue={reopenFromResolved}" in modal
    # The page rides along with every status, and survives a reload.
    assert "severity:    meta.severity    ?? null," in modal
    assert "severity: s.severity ?? null" in modal
    assert "__severity: reviewSeverity(ctx.tone)" in modal


def test_the_rail_layout_files_handled_items_under_resolved():
    rail = _RAIL.read_text(encoding="utf-8")
    assert "renderItemActions(it, c.forms, tone)" in rail
    assert "}, c.forms, tone)}" in rail
    assert "{renderResolved(hardResolved, \"hard\")}" in rail
    assert "{renderResolved(warnResolved, \"soft\")}" in rail
    # The heading is a page-level group like the warning tiers ("REQUIRED BEFORE
    # SUBMISSION"), not a card title; the rows sit in one card under it (owner, 9 Oct).
    resolved = rail[rail.index("const renderResolved = (rows, tone) => {"):]
    resolved = resolved[:resolved.index("\n  };\n")]
    # Hard Stops has no tiers: there it is a card like the hard-stop cards beside it
    # (owner, 9 Oct evening); Warnings keeps the tier heading.
    hard = resolved[resolved.index('if (tone === "hard") {'):resolved.index('return (\n      <div className="rr-tier rr-resolved">')]
    assert '<section className="rr-panel rr-resolved">' in hard
    assert re.search(r'className="rr-panel__head rr-panel__head--button"[\s\S]*?<span className="rr-panel__title">\s*Resolved\s*<span className="issue-count">', hard)
    assert '<div className="rr-tier rr-resolved">' in resolved
    assert re.search(r'<FoldButton className="rr-tier__head"[\s\S]*?\}>\s*Resolved\s*<span className="issue-count">', resolved)
    assert "{open && <section className=\"rr-panel\">{list}</section>}" in resolved
    # "Open again" is a real chip: the Dismiss chip's size and colours, plus an arrow.
    assert 'className="issue-status-btn rr-resolved__open"' in resolved
    assert "{!busy && <ReopenIcon />}" in resolved and '"Open again"' in resolved
    assert '{reopenKind(r) === "none" ? (' in resolved and "{NO_LONGER_APPLIES}" in resolved
    css = (_FRONT / "components" / "form" / "review" / "ReviewRailLayout.css").read_text(encoding="utf-8")
    chip = css[css.index(".rr-resolved__actions .rr-resolved__open {"):]
    chip = chip[:chip.index("}")]
    for rule in ("font-size: 10px;", "font-weight: 600;", "padding: 2px 8px;", "border-radius: 5px;",
                 "display: inline-flex;", "white-space: nowrap;"):
        assert rule in chip, rule
    # A dismissed hard stop still holds the score - the empty state says what raises
    # it, in the positive wording of Choice Electric #16 (9 Oct 2026).
    assert "Fix a dismissed hard stop's value to increase your Submission Quality Score (SQS)™." in rail
    for text in (rail, _UTIL.read_text(encoding="utf-8")):
        assert "—" not in text                       # no em-dashes in UI text
