"""Orbin 22 Sep feedback, item 16 (30 Sep 2026).

Client: "Stylistically, this should tuck under 'reviewed' or 'recommendations'
after it's been addressed." Screenshot: the editor side panel's red HARD STOPS
block ("Caps the package Submission Quality Score (SQS) at 60") still printing
"Policy term already expired ..." with a green "Resolved" chip and "Reopen" -
beside a Total Package Score of 84.

What was measured on the real code (not assumed):
  * "Resolve" / "Dismiss" are work-tracking only. `/api/issues/status` writes a
    status row and never runs the scorer, and nothing that scores reads a
    status. A stop marked resolved WITHOUT fixing its value still caps at 60.
  * "Open to fix" re-scores the session and clears the stop - but the editor's
    reply carried only the package HEADLINE, which the panel merged over the
    old payload, so `cap_applied` / `cap_hard_stops` kept the pre-fix values:
    84 on the number, "Caps ... at 60" on the block. The screenshot, exactly.

The fix, three parts:
  1. resolve / reopen ship the whole persisted package (`editor_package_sqs`)
     and each form's whole score (`new_sqs`) on the editor, as the answer route
     has since C2-C; the panel replaces instead of merging the headline.
  2. The red blocks print OPEN stops only. A handled stop moves to Reviewed,
     keeping its controls (and its Reopen); a fixed legacy stop is listed there
     too instead of in the Cross-Form panel. Each row renders once.
  3. The 60 is never silent: when every stop still holding the score is
     handled, a short note replaces the red block and names them.
"""
from __future__ import annotations

import asyncio
import copy
import json
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

import repositories.session_repository as sr
import routes.audit_routes as ar
import services.arq_service as arq
import services.audit_service as au
import services.issue_registry as ir
import services.sqs_service as sq
from models.schemas import IssueStatusRequest, ReopenIssueRequest, ResolveIssueRequest

HERE = Path(__file__).resolve().parent
_FRONTEND_SRC = HERE.parents[1] / "frontend" / "src"
_ACORD_MODAL = _FRONTEND_SRC / "components" / "form" / "AcordModal.jsx"
_UTIL = _FRONTEND_SRC / "utils" / "reviewedStops.js"
_EM_DASHES = ("\u2014", "\u2013")   # em dash, en dash

_SID = "sid-item16"
_UID = "u-item16"
_EXPIRED_CODE = "legacy_policy_term_expired"


def _mdY(dt):
    return dt.strftime("%m/%d/%Y")


def _producer(value):
    return {"value": value, "source": "producer", "confidence": "filled"}


def _expired_term():
    exp = datetime.now() - timedelta(days=90)
    return exp - timedelta(days=365), exp


def _row(**over):
    """A generated package whose producer-typed term ended 90 days ago - the
    hard stop in the client's screenshot, on the editor."""
    eff, exp = _expired_term()
    base = {
        "user_id": _UID,
        "facts": {
            "producer_name": "Best Agency", "applicant_name": "Acme LLC",
            "mailing_address": "1 Main St, Denver, CO 80202",
            "lines_of_business": "General Liability", "entity_type": "LLC",
            "contact_phone": "303-555-0100", "contact_name": "Pat Doe",
            "fein": "12-3456789", "operations_description": "Electrical contracting",
            "total_revenue": "$1,200,000", "num_employees": "12",
            "years_in_business": "8", "naics_code": "238210",
            "effective_date": _producer(_mdY(eff)),
            "expiration_date": _producer(_mdY(exp)),
        },
        "flags": {"has_general_liability": True},
        "hard_stops": [], "soft_stops": [],
        "recommendations": [{"form_id": "ACORD_125"}],
        "cross_form_issues": [], "structured_issues": [], "docs": [], "integrity": {},
        "generated_forms": {"ACORD_125": {
            "mapped": {"NamedInsured_FullName_A": "Acme LLC"},
            "confidence": {"NamedInsured_FullName_A": "ai_high"},
            "schema": {"NamedInsured_FullName_A": {"ft": "/Tx", "tu": "Enter name"}},
        }},
        "selected_form_ids": ["ACORD_125"], "underwriting_consistency": {},
    }
    base.update(over)
    return base


class _Session:
    """The REAL recalc and route code against an in-memory row; every audit /
    DB side effect is stubbed. `statuses` records what the status route wrote."""

    def __init__(self, row):
        self.store = copy.deepcopy(row)
        self.statuses = []

    async def _get(self, _sid):
        return copy.deepcopy(self.store)

    async def _upd(self, _sid, payload, delete_facts=None):
        for k, v in (payload or {}).items():
            self.store[k] = copy.deepcopy(v)
        for k in (delete_facts or []):
            self.store.get("facts", {}).pop(k, None)
        return True

    def run(self, coro_fn, *args, **kwargs):
        async def _none(*_a, **_k):
            return None

        async def _empty(*_a, **_k):
            return []

        async def _status(**kw):
            self.statuses.append(kw)
            return True

        async def _no_credits(*_a, **_k):
            return 0, []

        with patch.object(sr, "get_processing_session", self._get), \
             patch.object(sr, "upd_processing_session", self._upd), \
             patch.object(ar, "get_processing_session", self._get), \
             patch.object(ar, "log_field_change", _none), \
             patch.object(ar, "set_issue_status", _status), \
             patch.object(au, "log_audit_event", _none), \
             patch.object(au, "log_sqs_snapshot_if_changed", _none), \
             patch.object(au, "get_open_recommendations", _empty), \
             patch.object(au, "mark_recommendation_resolved", _none), \
             patch.object(au, "sync_recommendation_cards", _none), \
             patch.object(au, "active_score_credits", _no_credits):
            return asyncio.run(coro_fn(*args, **kwargs))

    def recalc(self):
        return self.run(arq.recalculate_session_scores, _SID)

    def body(self, route, req):
        return json.loads(self.run(route, req, current_user={"id": _UID}).body)


def _expired_item(pkg):
    items = [i for i in (pkg.get("cap_hard_stop_items") or [])
             if str(i.get("message", "")).startswith("Policy term already expired")]
    assert len(items) == 1, pkg.get("cap_hard_stop_items")
    return items[0]


@pytest.fixture()
def capped():
    s = _Session(_row())
    s.recalc()
    pkg = s.store["package_sqs"]
    # The fixture is the screenshot's shape, or every test below is vacuous.
    assert pkg["cap_applied"] == 60, pkg.get("cap_reason")
    assert pkg["package_sqs_score"] <= 60
    assert pkg["cap_reason"].startswith("Policy term already expired")
    return s


# ══ 1. Measured: what "Resolved" does and does not do ═════════════════════════

def test_the_stop_carries_an_open_to_fix_row(capped):
    item = _expired_item(capped.store["package_sqs"])
    assert item["code"] == _EXPIRED_CODE
    assert (item.get("resolution") or {}).get("mode") == "field"
    assert item.get("forms") == []


def test_marking_a_stop_resolved_never_moves_the_cap(capped):
    """The real status route, then the real recalculation: the stop still caps
    the package at 60 with the same reason. This is why the panel must keep
    explaining a 60 whose stop was only marked."""
    pkg_before = copy.deepcopy(capped.store["package_sqs"])
    item = _expired_item(pkg_before)
    out = capped.body(ar.set_issue_status_route, IssueStatusRequest(
        session_id=_SID, issue_id="issf_x", status="resolved",
        rule_code=item["code"], message=item["message"]))
    assert out == {"success": True, "issue_id": "issf_x", "status": "resolved"}
    assert capped.statuses and capped.statuses[0]["status"] == "resolved"
    capped.recalc()
    pkg_after = capped.store["package_sqs"]
    assert pkg_after["cap_applied"] == 60
    assert pkg_after["cap_reason"] == pkg_before["cap_reason"]
    assert pkg_after["package_sqs_score"] == pkg_before["package_sqs_score"]
    assert _expired_item(pkg_after)["message"] == item["message"]


def test_nothing_that_scores_reads_a_resolution_status():
    """Structural twin: the status table is only ever touched by the status
    routes. If a scorer starts reading it, the "still capped" note becomes a
    lie and this test says so."""
    for mod in (sq, arq):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        for needle in ("submission_issue_status", "get_issue_statuses", "issue_statuses"):
            assert needle not in src, f"{mod.__name__} reads {needle}"


# ══ 2. Measured: the root cause of the stale block ════════════════════════════

def _fix_the_term(s):
    new_exp = _mdY(datetime.now() + timedelta(days=300))
    return s.body(ar.resolve_issue, ResolveIssueRequest(
        session_id=_SID, mode="field", field="expiration_date", value=new_exp,
        code=_EXPIRED_CODE, issue_id="issf_expired"))


def test_open_to_fix_clears_the_cap_and_the_headline_alone_would_leave_it(capped):
    before = copy.deepcopy(capped.store["package_sqs"])
    out = _fix_the_term(capped)
    assert out["success"] is True
    persisted = capped.store["package_sqs"]
    assert persisted["cap_applied"] != 60
    assert not persisted.get("cap_hard_stops")
    assert out["new_package_sqs_score"] == persisted["package_sqs_score"] > 60
    # What the editor used to do with this reply: merge the headline. The
    # result is the screenshot - a score above 60 under a block that still
    # says the package is capped at 60 by the stop just fixed.
    merged = {**before, "package_sqs_score": out["new_package_sqs_score"],
              "tier": out["new_package_tier"]}
    assert merged["package_sqs_score"] > 60 and merged["cap_applied"] == 60
    assert merged["cap_reason"].startswith("Policy term already expired")


def test_the_editor_reply_ships_the_whole_package_and_form_scores(capped):
    out = _fix_the_term(capped)
    assert out["editor_package_sqs"] == capped.store["package_sqs"]
    assert out["editor_package_sqs"]["package_sqs_score"] == out["new_package_sqs_score"]
    form = out["updated_forms"]["ACORD_125"]
    assert form["new_sqs"] == capped.store["generated_forms"]["ACORD_125"]["sqs"]
    assert form["new_sqs_score"] == form["new_sqs"]["sqs_score"]
    # the pre-form score stays pre-form only (Step 2, item 2); the Key Details
    # list now rides along after generation, for the package page (Orbin item
    # 1, 1 Oct 2026 - the TEST changed)
    assert "package_sqs" not in out
    assert "key_details" in out


def test_the_editor_reopen_reply_ships_them_too(capped):
    _fix_the_term(capped)
    back = capped.body(ar.reopen_issue, ReopenIssueRequest(
        session_id=_SID, code=_EXPIRED_CODE, issue_id="issf_expired",
        message="Policy term already expired"))
    assert back["cleared"] is True
    assert back["editor_package_sqs"] == capped.store["package_sqs"]
    assert back["new_package_sqs_score"] == capped.store["package_sqs"]["package_sqs_score"]
    assert back["updated_forms"]["ACORD_125"]["new_sqs"] == \
        capped.store["generated_forms"]["ACORD_125"]["sqs"]
    assert "package_sqs" not in back


@pytest.mark.parametrize("over", [
    {"generated_forms": {}, "selected_form_ids": []},
    {"generated_forms": {}, "selected_form_ids": ["ACORD_125"]},
], ids=["pre-form", "clarity"])
def test_off_the_editor_nothing_new_ships(over):
    s = _Session(_row(**over))
    s.recalc()
    out = _fix_the_term(s)
    assert out["success"] is True
    assert "editor_package_sqs" not in out
    assert all("new_sqs" not in v for v in (out.get("updated_forms") or {}).values())


@pytest.mark.parametrize("sess", [
    {}, {"generated_forms": {}}, {"generated_forms": None},
    {"generated_forms": {"ACORD_125": {}}},
    {"generated_forms": {"ACORD_125": {}}, "package_sqs": None},
    {"generated_forms": {"ACORD_125": {}}, "package_sqs": "junk"},
    {"generated_forms": {"ACORD_125": {}}, "package_sqs": {"tier": "x"}},
])
def test_the_refresh_helper_is_empty_unless_there_is_a_scored_editor_package(sess):
    assert ar._editor_score_refresh(sess) == {}


def test_the_refresh_helper_never_raises():
    class _Boom(dict):
        def get(self, *_a, **_k):
            raise RuntimeError("boom")
    assert ar._editor_score_refresh(_Boom()) == {}
    pkg = {"package_sqs_score": 72, "cap_applied": None}
    assert ar._editor_score_refresh({"generated_forms": {"A": {}}, "package_sqs": pkg}) == \
        {"editor_package_sqs": pkg}


def test_both_handlers_spread_the_editor_refresh():
    import ast
    tree = ast.parse(Path(ar.__file__).read_text(encoding="utf-8"))
    handlers = {n.name: n for n in ast.walk(tree)
                if isinstance(n, ast.AsyncFunctionDef) and n.name in ("resolve_issue", "reopen_issue")}
    assert set(handlers) == {"resolve_issue", "reopen_issue"}
    for name, fn in handlers.items():
        spreads = [v for n in ast.walk(fn) if isinstance(n, ast.Dict)
                   for k, v in zip(n.keys, n.values)
                   if k is None and isinstance(v, ast.Call)
                   and getattr(v.func, "id", None) == "_editor_score_refresh"]
        assert spreads, name
        keys = {k.value for n in ast.walk(fn) if isinstance(n, ast.Dict)
                for k in n.keys if isinstance(k, ast.Constant)}
        assert "new_sqs" in keys, name


# ══ 3. The panel logic, run for real under node ═══════════════════════════════

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


def test_package_reasons_follow_the_blocks_own_rule(tmp_path):
    out = _node(tmp_path, """
console.log(JSON.stringify([
  R.packageCapReasons(null),
  R.packageCapReasons({cap_applied: 85, cap_reason: "x"}),
  R.packageCapReasons({cap_applied: null, cap_hard_stops: ["a"]}),
  R.packageCapReasons({cap_applied: 60, cap_reason: "r"}),
  R.packageCapReasons({cap_applied: 60, cap_reason: "r", cap_hard_stops: ["a", "b"]}),
  R.packageCapReasons({cap_applied: 60, cap_reason: "r", cap_hard_stops: []}),
  R.packageCapReasons({cap_applied: 60}),
]));""")
    assert out == [[], [], [], ["r"], ["a", "b"], ["r"], []]


def test_handled_stops_leave_the_block_and_open_ones_stay(tmp_path):
    out = _node(tmp_path, """
const items = [
  {message: "A", code: "legacy_a", forms: []},
  {message: "B", code: "legacy_b", forms: []},
  {message: "C", code: "legacy_c", forms: ["ACORD_140"]},
];
const st = {"A|": "resolved", "B|": "dismissed", "C|ACORD_140": "open"};
const r = R.splitCapStops(["A", "B", "C", "D"], items, {idOf, statusOf: (i) => st[i]});
console.log(JSON.stringify({
  open: r.open.map((x) => [x.message, x.iid, x.item ? x.item.code : null]),
  handled: r.handled.map((x) => [x.message, x.iid, x.status]),
}));""")
    assert out["open"] == [["C", "C|ACORD_140", "legacy_c"], ["D", None, None]]
    assert out["handled"] == [["A", "A|", "resolved"], ["B", "B|", "dismissed"]]


def test_a_form_block_keys_its_items_the_way_the_control_does(tmp_path):
    """The per-form block always gave an item with no forms its own form; the
    id must be computed on THAT object or the status never matches."""
    out = _node(tmp_path, """
const items = [{message: "G", code: "legacy_g", forms: []},
               {message: "H", code: "legacy_h", forms: ["ACORD_125"]}];
const st = {"G|ACORD_140": "resolved", "H|ACORD_125": "resolved"};
const r = R.splitCapStops(["G", "H"], items,
  {idOf, statusOf: (i) => st[i], fallbackForms: ["ACORD_140"]});
const bare = R.splitCapStops(["G"], items, {idOf, statusOf: (i) => st[i]});
console.log(JSON.stringify({
  handled: r.handled.map((x) => [x.iid, x.item.forms]),
  open: r.open.length, bareOpen: bare.open.map((x) => x.iid),
  untouched: items[0].forms,
}));""")
    assert out["handled"] == [["G|ACORD_140", ["ACORD_140"]], ["H|ACORD_125", ["ACORD_125"]]]
    assert out["open"] == 0
    assert out["bareOpen"] == ["G|"]
    assert out["untouched"] == []   # the server's row is never mutated


def test_empty_and_malformed_inputs_are_all_open_or_empty(tmp_path):
    out = _node(tmp_path, """
const s = (m, i, o) => { const r = R.splitCapStops(m, i, o); return [r.open.length, r.handled.length]; };
console.log(JSON.stringify([
  s(undefined, undefined, undefined), s(null, null, {}), s([], [], {idOf}),
  s(["A"], null, {idOf, statusOf: () => "resolved"}),
  s(["A"], [null, {message: "A"}], {statusOf: () => "resolved"}),
  s(["A"], [{message: "A"}], {idOf, statusOf: () => "weird"}),
  s(["A"], [{message: "A"}], {idOf, statusOf: () => "resolved"}),
  s(["A", "A"], [{message: "A"}], {idOf, statusOf: () => "resolved"}),
]));""")
    assert out == [[0, 0], [0, 0], [0, 0], [1, 0], [1, 0], [1, 0], [0, 1], [0, 2]]


def test_each_row_renders_once(tmp_path):
    out = _node(tmp_path, """
const rows = R.uniqueRows([{iid: "a", scope: "package"}, {iid: "b"}, {iid: "a", scope: "form"},
                           null, {iid: null}, {}]);
const ghosts = [
  {issue_id: "a", code: "legacy_x"},            // already a Reviewed row
  {issue_id: "g1", code: "legacy_policy_term_expired"},
  {issue_id: "g2", code: "tier1_missing_Contact information"},
  {issue_id: "g3", code: "umbrella_below_gl"},  // a cross-form validation
  {issue_id: "g4", code: null},                 // unknown source: left where it was
  {issue_id: "g5"}, null,
];
const g = R.routeGhostIssues(ghosts, new Set(rows.map((r) => r.iid)));
const g2 = R.routeGhostIssues(ghosts, ["a"]);
const g3 = R.routeGhostIssues(undefined, undefined);
console.log(JSON.stringify({
  rows: rows.map((r) => [r.iid, r.scope]),
  reviewed: g.reviewed.map((x) => x.issue_id), cross: g.crossForm.map((x) => x.issue_id),
  arr: [g2.reviewed.length, g2.crossForm.length], empty: [g3.reviewed.length, g3.crossForm.length],
}));""")
    assert out["rows"] == [["a", "package"], ["b", None]]
    assert out["reviewed"] == ["g1", "g2"]
    assert out["cross"] == ["g3", "g4", "g5"]
    assert out["arr"] == [2, 3] and out["empty"] == [0, 0]


def test_the_still_capped_note(tmp_path):
    out = _node(tmp_path, """
const r = (status) => ({iid: status + Math.random(), status});
console.log(JSON.stringify([
  R.stillCappedNote([], "package"), R.stillCappedNote(null, "form"),
  R.stillCappedNote([r("resolved")], "package"),
  R.stillCappedNote([r("dismissed")], "form"),
  R.stillCappedNote([r("resolved"), r("dismissed")], "package"),
  R.stillCappedNote([r("resolved"), r("resolved"), r("resolved")], "form"),
]));""")
    assert out[0] == "" and out[1] == ""
    assert out[2] == ("The package is still capped at 60 by an item you marked resolved - "
                      "reopen it under Reviewed, or fix the value.")
    assert out[3] == ("This form is still capped at 60 by an item you marked dismissed - "
                      "reopen it under Reviewed, or fix the value.")
    assert out[4].startswith("The package is still capped at 60 by 2 items you marked resolved or dismissed")
    assert out[4].endswith("reopen them under Reviewed, or fix the value.")
    assert out[5].startswith("This form is still capped at 60 by 3 items you marked resolved - reopen them")
    for text in out:
        assert not any(d in text for d in _EM_DASHES)


@pytest.mark.parametrize("status", [None, "open", "resolved", "dismissed"])
def test_a_60_is_never_silent_on_the_real_payload(capped, tmp_path, status):
    """The package the REAL scorer persisted, through the REAL panel helpers,
    in every status the stop can carry: the package is capped at 60, so the
    screen must either print the stop in the red block or print the note."""
    pkg = capped.store["package_sqs"]
    item = _expired_item(pkg)
    out = _node(tmp_path, f"""
const pkg = {json.dumps(pkg)};
const st = {json.dumps({f"{item['message']}|": status} if status else {})};
const r = R.splitCapStops(R.packageCapReasons(pkg), pkg.cap_hard_stop_items,
  {{idOf, statusOf: (i) => st[i]}});
console.log(JSON.stringify({{open: r.open.map((x) => x.message), handled: r.handled.length,
  note: R.stillCappedNote(r.handled, "package")}}));""")
    handled = status in ("resolved", "dismissed")
    assert out["open"] == ([] if handled else [item["message"]])
    assert out["handled"] == (1 if handled else 0)
    assert bool(out["open"]) or out["note"].startswith("The package is still capped at 60 by an item")


def test_once_fixed_the_block_is_gone_and_the_stop_is_under_reviewed(capped, tmp_path):
    out_fix = _fix_the_term(capped)
    pkg = out_fix["editor_package_sqs"]
    ghost = {"issue_id": "issf_expired", "code": _EXPIRED_CODE,
             "message": "Policy term already expired", "forms": []}
    out = _node(tmp_path, f"""
const pkg = {json.dumps(pkg)};
const g = R.routeGhostIssues([{json.dumps(ghost)}], new Set());
console.log(JSON.stringify({{reasons: R.packageCapReasons(pkg),
  reviewed: g.reviewed.map((x) => x.issue_id), cross: g.crossForm.length}}));""")
    assert out == {"reasons": [], "reviewed": ["issf_expired"], "cross": 0}


# ══ 4. The legacy-engine namespaces, both sides ══════════════════════════════

def _js_prefixes():
    src = _UTIL.read_text(encoding="utf-8")
    line = src[src.index("export const LEGACY_ENGINE_CODE_PREFIXES"):]
    line = line[:line.index(";")]
    return json.loads(line[line.index("["):])


def test_every_legacy_engine_code_is_routed_to_reviewed():
    prefixes = tuple(_js_prefixes())
    assert prefixes == ("legacy_", "tier1_missing_")
    codes = [row[3] for row in ir._LEGACY_MESSAGE_RULES]
    assert codes and all(c and c.startswith(prefixes) for c in codes)
    for label in ir._tier1_label_to_facts():
        code = ir.classify_legacy(ir._TIER1_MSG_PREFIX + label, "hard_stop")[0]
        assert code and code.startswith(prefixes), label


def test_no_cross_form_code_is_mistaken_for_one():
    prefixes = tuple(_js_prefixes())
    for table in (ir.CLUSTER_MAP, ir.RESOLUTION_MAP):
        clash = [c for c in table if c.startswith(prefixes)]
        assert not clash, clash


# ══ 5. The panel, pinned on its source ═══════════════════════════════════════

def _modal():
    return _ACORD_MODAL.read_text(encoding="utf-8")


def _between(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i)]


def test_the_package_block_prints_open_stops_and_never_a_silent_60():
    block = _between(_modal(), "{packageSqs && packageSqs.cap_applied === 60 && (() => {",
                     "TOTAL PACKAGE SCORE (collapsible")
    assert "const { open, handled } = pkgCapSplit;" in block
    assert "if (!open.length && !handled.length) return null;" in block
    assert 'stillCappedNote(handled, "package")' in block
    assert "open.map((r, i) =>" in block and "• {r.message}" in block
    # Item 16 (1 Oct): a handled stop's sentence prints once, on its Reviewed
    # row ("Still caps the package score at 60") - the block keeps the note only.
    assert "handled.map((r, i) =>" not in block
    assert "Caps the package Submission Quality Score (SQS) at 60" in block
    assert "itemResolveAndStatus(r.item, r.item.forms || [])" in block


def test_the_form_block_prints_open_stops_and_never_a_silent_60():
    src = _modal()
    block = _between(src, "{formCapSplit.open.length > 0 && (", "RECOMMENDATIONS (collapsible")
    assert "Caps this form's Submission Quality Score (SQS) at 60" in block
    assert "formCapSplit.open.map((r, i) =>" in block
    assert "itemResolveAndStatus(r.item, activeFormId ? [activeFormId] : [])" in block
    assert "{formCapSplit.open.length === 0 && formCapSplit.handled.length > 0 && (" in block
    assert 'stillCappedNote(formCapSplit.handled, "form")' in block
    # the old unconditional render is gone
    assert "{activeCapStops.length > 0 && (" not in src


def test_the_split_is_keyed_like_the_controls():
    src = _modal()
    prep = _between(src, "const _capStatusOf = ", "const activeKeyIssues")
    assert "splitCapStops(packageCapReasons(packageSqs)," in prep
    assert "packageSqs?.cap_hard_stop_items, { idOf: issueIdOf, statusOf: _capStatusOf });" in prep
    assert "fallbackForms: activeFormId ? [activeFormId] : []" in prep
    assert "routeGhostIssues(ghostIssues, new Set(reviewedStops.map((r) => r.iid)))" in prep
    assert "dismissedRecDetails.size + reviewedStops.length + reviewedGhosts.length" in prep
    # Reviewed is session-wide: every generated form's handled stops, each keyed
    # with its own form exactly as that form's block keys it
    assert "Object.entries(generatedForms || {}).flatMap(([fid, f]) => splitCapStops(" in prep
    assert "fallbackForms: [fid] }," in prep
    assert '.handled.map((r) => ({ ...r, scope: "form", formId: fid }))' in prep
    # Key Issues still drop every cap sentence, handled or not
    assert ".filter((s) => !activeCapStops.includes(s));" in src


def test_reviewed_lists_handled_and_fixed_stops_with_their_reopen():
    src = _modal()
    sec = _between(src, "{reviewedCount > 0 && (", "SENT QUESTIONNAIRES")
    assert "title={`Reviewed (${reviewedCount})`}" in sec
    assert 'tooltip="Items you\'ve already answered, resolved or dismissed."' in sec
    held = _between(sec, "reviewedStops.map((r) =>", "reviewedGhosts.map((g) =>")
    assert "itemResolveAndStatus(r.item, r.item.forms || [])" in held
    assert "`Still caps the ${shortFormLabel(r.formId)} score at 60`" in held
    assert "Still caps the package score at 60" in held
    fixed = _between(sec, "reviewedGhosts.map((g) =>", "Array.from(dismissedRecDetails.entries())")
    assert "<IssueStatusControl" in fixed and "onSet={handleReopenIssue}" in fixed
    assert "reopenNotices.get(g.issue_id)" in fixed and "reopeningIds.has(g.issue_id)" in fixed
    # recommendations still render beneath, unchanged
    assert "Array.from(dismissedRecDetails.entries()).map(([rid, d]) =>" in sec


def test_the_cross_form_panel_keeps_only_its_own_resolved_rows():
    src = _modal()
    panel = _between(src, "{(crossIssues.length > 0 || crossFormGhosts.length > 0) && (",
                     "REVIEWED (renamed from Dismissed)")
    assert "crossFormGhosts.map((g, gi) =>" in panel
    assert "Resolved ({crossFormGhosts.length})" in panel
    assert "ghostIssues" not in panel


def test_the_panel_replaces_scores_from_a_resolve_or_reopen():
    src = _modal()
    body = _between(src, "const _applyCrossIssuePanelUpdate = (data) => {", "const handleIssueResolved")
    assert "sqs: upd.new_sqs ? upd.new_sqs : {" in body
    # order: pre-form door, then the editor's whole package, then the headline
    a = body.index("if (data.package_sqs !== undefined) {")
    b = body.index("} else if (data.editor_package_sqs) {")
    c = body.index("} else if (data.new_package_sqs_score != null) {")
    assert a < b < c
    assert "setPackageSqs(data.editor_package_sqs);" in body


def test_new_copy_carries_no_em_dash():
    src = _modal()
    for text in ("Still caps the ${shortFormLabel(r.formId)} score at 60",
                 "Still caps the package score at 60",
                 "Items you've already answered, resolved or dismissed."):
        assert text in src and not any(d in text for d in _EM_DASHES)
    util = _UTIL.read_text(encoding="utf-8")
    assert not any(d in util for d in _EM_DASHES)
