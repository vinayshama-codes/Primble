"""Recommendations get a Resolved list, and the narrative window reads meaning (owner, 13 Oct 2026).

1. "on the preform screen i need a resolved section similar to hard stops and warnings and
   also they can be reopened and score goes back, basically same thing" - meaning the
   Recommendations page. A "Raise your score" / "Your forms will need" fix was sent with no
   id, so the server kept no record of what it changed and nothing could be taken back. Now
   the fix travels with the row's own id ("rec:..."), the server files the changes under it
   (services/issue_fix_undo.py), a row the save FIXED moves to a collapsed "Resolved (n)"
   (status page "recommendation"), and "Open again" goes through the one reopen door: the
   values and the points come back off.

2. "on navigate, i pasted the paragraph and only the safety or loss control program is
   ticked". The paragraph covered all 20 options by the scorer's own phrases; a chip ticked
   only when its sentence starter appeared word for word. Each option now carries the
   phrases its check reads and the window ticks what the text covers.

The route tests drive the REAL resolve / reopen routes and scorer through the in-memory
session of tests/test_reopen_takes_the_fix_back_9oct.py; the frontend rules run under node.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from test_reopen_takes_the_fix_back_9oct import _Session, _mdY, _producer, _row  # noqa: E402

import services.issue_fix_undo as undo                                           # noqa: E402
from services import sqs_service as sq                                           # noqa: E402
from services.review_recommendations import with_fix_routes                      # noqa: E402

_FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"
_REC = _FRONT / "utils" / "recommendations.js"
_RESOLVED = _FRONT / "utils" / "resolvedIssues.js"
_FIXP = _FRONT / "utils" / "fixProgress.js"
_NODE = shutil.which("node") is None

# The paragraph the owner pasted on run 841bb967 (Choice Electric).
_PARAGRAPH = (
    "Account overview: Choice Electric LLC is a family-owned commercial electrical contractor based in "
    "Denver, Colorado, in business since April 2008 (18 years) under the same ownership. Operations: new "
    "construction, tenant-finish and service electrical work (wiring, lighting, power distribution and panel "
    "upgrades) inside commercial and light-industrial buildings for general contractors and property managers "
    "across the Denver metro area. Scope of work: about 70% new construction and tenant finish and 30% service "
    "and repair; no residential work. Location details: one premises at 4800 Washington St, Denver, CO 80216 "
    "with two buildings - a frame office and electrical shop, and a light-steel building for material and "
    "equipment storage. Management experience: the owners are licensed master electricians with more than 20 "
    "years in the trade each, supported by experienced project managers and estimators. Employee and payroll "
    "context: about 100 employees; total payroll is $2,626,500 and annual revenue is about $4,500,000. WC "
    "payroll and class codes: 5190 electrical wiring within buildings $2,000,000, 8742 outside salespersons "
    "$426,500 and 8810 clerical $200,000, all in Colorado. EMOD / XMOD: experience modification factor 1.08 "
    "(NCCI). Risk controls: written safety program with weekly toolbox talks, OSHA 10/30 and NFPA 70E "
    "arc-flash training, lockout/tagout procedures, and annual MVR checks for every driver of the 17-vehicle "
    "service fleet. Loss history: no claims or losses in the past five years on any line. Coverage "
    "discussion: renewal of the current program - Amerisure package (property, general liability, inland "
    "marine, crime, employee benefits liability), business auto, umbrella and workers compensation; Travelers "
    "excess; Chubb cyber and employment practices liability - at the same limits. Marketing reason: we are "
    "marketing the account at renewal for competitive terms on the same program."
)


def _node(tmp_path, imports: dict, body: str) -> dict:
    head = "".join(f"import * as {name} from {json.dumps(path.as_uri())};\n" for name, path in imports.items())
    script = tmp_path / "check.mjs"
    script.write_text(head + body + "\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _all_gaps():
    return sq.narrative_gap_options({k: False for k in sq.NARRATIVE_COMPONENT_LABELS}, "")


# ══ 1. The narrative window ticks what the text covers ══════════════════════
def test_every_option_carries_the_phrases_its_own_check_reads():
    gaps = _all_gaps()
    assert len(gaps) == len(sq.NARRATIVE_COMPONENT_LABELS) + len(sq._NARRATIVE_SUBSTANCE_SIGNALS)
    for g in gaps:
        kind, key = g["key"].split(":", 1)
        table = sq._NARRATIVE_SCORE_SIGNALS if kind == "topic" else sq._NARRATIVE_SUBSTANCE_SIGNALS
        assert g["phrases"] == list(table[key]), g["key"]
        # finishing the option's own starter covers it (the starter carries a phrase)
        if kind == "depth":
            assert any(p in g["starter"].lower() for p in g["phrases"]), g["key"]


def test_the_pasted_paragraph_covers_what_the_score_credits():
    """The scorer credits every topic and every depth category from the paragraph - the
    phrases the window now reads are exactly the ones that decide that."""
    text = _PARAGRAPH.lower()
    comps = sq._score_narrative_components(_PARAGRAPH)
    for g in _all_gaps():
        kind, key = g["key"].split(":", 1)
        covered = any(p in text for p in g["phrases"])
        credited = comps[key] if kind == "topic" else key not in [
            k for k, ph in sq._NARRATIVE_SUBSTANCE_SIGNALS.items() if not any(p in text for p in ph)]
        assert covered == credited, g["key"]
    assert sq.narrative_gap_options(comps, _PARAGRAPH) == []        # nothing left to ask after the save
    assert sq._score_narrative_substance(_PARAGRAPH) == 100


@pytest.mark.skipif(_NODE, reason="node is not installed")
def test_the_window_ticks_all_twenty_for_the_paragraph(tmp_path):
    gaps = _all_gaps()
    o = _node(tmp_path, {"F": _FIXP}, (
        f"const gaps = {json.dumps(gaps)};\n"
        f"const para = {json.dumps(_PARAGRAPH)};\n"
        "const cov = (t) => { const c = F.textForCoverage(t, gaps); return gaps.filter(g => F.gapCovered(c, g)).map(g => g.key); };\n"
        "const starter = gaps.find(g => g.key === 'depth:risk_controls').starter;\n"
        "const own = gaps.find(g => g.key === 'depth:ownership_or_experience').starter;\n"
        "console.log(JSON.stringify({\n"
        "  para: cov(para).length,\n"
        "  exact: gaps.filter(g => g.starter && para.includes(g.starter)).map(g => g.key),\n"
        "  empty: cov('').length,\n"
        # a ticked starter nobody finished says nothing - it covers no option, not even its own
        "  unfinished: cov(own),\n"
        "  unfinishedTbd: cov(own + 'TBD'),\n"
        # finished, it covers its own option and whatever else its words cover
        "  finished: cov(own + '2008 under the same ownership'),\n"
        "  upper: cov(para.toUpperCase()).length,\n"
        "  noPhrases: F.gapCovered('anything', {key: 'x'}),\n"
        "}));"))
    assert o["para"] == 20                           # the owner's paste: all twenty ticked
    assert o["exact"] == ["depth:risk_controls"]     # the old rule: one
    assert o["empty"] == 0
    assert o["unfinished"] == [] and o["unfinishedTbd"] == []
    assert "depth:ownership_or_experience" in o["finished"]
    assert o["upper"] == 20                          # case never matters (the server lowers both)
    assert o["noPhrases"] is False                   # an older option without phrases is never ticked


def test_the_window_shows_coverage_and_keeps_its_own_words():
    modal = (_FRONT / "components" / "form" / "ResolutionModal.jsx").read_text(encoding="utf-8")
    assert "Still missing - tick to add a starter" in modal and "resolution.gaps.map((g) =>" in modal
    assert "gapCovered(narrativeCoverage, g)" in modal
    assert "const on = starterIn || coveredByText;" in modal
    assert "disabled={busy || !g.starter || locked}" in modal       # the producer's own words are not unticked
    assert "Your text covers all of these." in modal
    assert "—" not in modal                                    # no em-dashes in UI text


# ══ 2. Recommendations: fix, Resolved, Open again - the score comes back ═════
def _property_package():
    row = _row(generated_forms={}, selected_form_ids=[])
    row["facts"]["effective_date"] = _producer(_mdY(datetime.now() - timedelta(days=165)))
    row["facts"]["expiration_date"] = _producer(_mdY(datetime.now() + timedelta(days=200)))
    row["flags"]["has_property_coverage"] = True
    s = _Session(row)
    s.recalc()
    return s


# A row with points on this package: the loss-history answer (+5). The property rows add
# nothing here - the pillar is 0 until its Minimum Viable COPE is answered, so they are
# not listed (the page's own rule).
_LOSS = "loss_history_no_prior_losses_indicator"
_NO_LOSSES = "No - no claims or losses in the past 5 years"


def _screen_package(s):
    """What the review screen holds: the stored package with its fix routes."""
    return with_fix_routes(s.store["package_sqs"], s.store["facts"])


@pytest.mark.skipif(_NODE, reason="node is not installed")
def test_a_score_row_fixed_from_its_window_is_resolved_and_open_again_takes_the_points_back(tmp_path):
    s = _property_package()
    before = s.score()
    before_facts = json.loads(json.dumps(s.store["facts"]))
    # The screen's own row and the fix window it opens - ids from the frontend rules.
    o = _node(tmp_path, {"R": _REC}, (
        f"const pkg = {json.dumps(_screen_package(s))};\n"
        "const rows = R.scoreItems(pkg).map(it => ({id: it.id, issue: R.scoreFixIssue(it)}));\n"
        "console.log(JSON.stringify(rows));"))
    loss = next(r for r in o if r["issue"]["resolution"].get("facts") == [_LOSS])
    iid, item_id = loss["issue"]["issue_id"], loss["id"]
    assert iid == f"rec:{item_id}" and iid.startswith("rec:score:loss_history_alignment:")

    out = s.fix(iid, mode="field", field=_LOSS, value=_NO_LOSSES)
    assert out["success"] is True and s.score() > before                 # the fix earned points
    assert iid in undo.load_receipts(s.store)                             # ...and is on file under the row

    judged = _node(tmp_path, {"R": _REC}, (
        f"const pkg = {json.dumps(_screen_package(s))};\n"
        f"const st = R.recommendationFixState('score', {json.dumps(item_id)}, {{packageSqs: pkg}});\n"
        f"const live = [...R.liveRecommendationIds({{packageSqs: pkg}})];\n"
        f"const rows = R.recommendationResolvedRows({{statusEntries: [[{json.dumps(iid)}, "
        "{status: 'resolved', message: 'Loss History: No loss history provided', severity: 'recommendation'}]], "
        "liveIds: new Set(live)});\n"
        f"console.log(JSON.stringify({{st, live: live.includes({json.dumps(iid)}), rows}}));"))
    assert judged["st"] == "fixed" and judged["live"] is False
    assert [r["iid"] for r in judged["rows"]] == [iid] and judged["rows"][0]["kind"] == "score"

    back = s.reopen(iid)
    assert back["cleared"] is True
    assert s.score() == before                                            # the points came off again
    assert s.store["facts"] == before_facts                               # the value it added is gone
    assert undo.load_receipts(s.store) == {}
    again = _node(tmp_path, {"R": _REC}, (
        f"const pkg = {json.dumps(_screen_package(s))};\n"
        f"console.log(JSON.stringify({{live: [...R.liveRecommendationIds({{packageSqs: pkg}})].includes({json.dumps(iid)})}}));"))
    assert again["live"] is True                                          # the row is back in its list


def test_a_narrative_row_comes_back_with_its_points():
    s = _property_package()
    before = s.score()
    iid = "rec:score:narrative_quality:fact:additional_remarks_text"
    out = s.fix(iid, mode="narrative", text=_PARAGRAPH)
    assert out["success"] is True and s.score() > before
    back = s.reopen(iid)
    assert back["cleared"] is True and s.score() == before
    assert "additional_remarks_text" not in s.store["facts"]


def test_a_value_changed_after_the_fix_is_never_erased_by_open_again():
    s = _property_package()
    iid = f"rec:score:loss_history_alignment:fact:{_LOSS}"
    s.fix(iid, mode="field", field=_LOSS, value=_NO_LOSSES)
    later = sq._fv(s.store["facts"], _LOSS)
    s.fix("iss-other", mode="field", field=_LOSS, value="Yes - we have had claims or losses")   # a later change
    assert sq._fv(s.store["facts"], _LOSS) != later
    back = s.reopen(iid)
    assert back["cleared"] is False and back["changed_since"] is True
    assert sq._fv(s.store["facts"], _LOSS) != later                       # the later answer stands


def test_a_status_is_filed_under_the_recommendations_page():
    import services.audit_service as au
    assert au.ISSUE_STATUS_PAGES == ("hard", "warning", "recommendation")
    src = (Path(au.__file__)).read_text(encoding="utf-8")
    assert "severity = severity if severity in ISSUE_STATUS_PAGES else None" in src


@pytest.mark.skipif(_NODE, reason="node is not installed")
def test_what_counts_as_fixed(tmp_path):
    o = _node(tmp_path, {"R": _REC}, (
        "const row = (p, f, extra = {}) => ({pillar: p, field: f, answer_mode: 'field', action: 'a', points_available: 5, ...extra});\n"
        "const pkg = {top_recommendations: [row('property_integrity', 'distance_to_hydrant'), row('exposure_consistency', 'gl_each_occurrence')]};\n"
        "const id = R.scoreItems(pkg)[0].id;\n"
        "const dry = (items, checked = ['ACORD_140'], status = 'ready') => ({status, checked_forms: checked.map(f => ({form_id: f})), forms: [{form_id: 'ACORD_140', items}]});\n"
        "const out = {};\n"
        "out.stillAsked = R.recommendationFixState('score', id, {packageSqs: pkg});\n"
        "out.gone = R.recommendationFixState('score', id, {packageSqs: {top_recommendations: [pkg.top_recommendations[1]]}});\n"
        "out.noPackage = R.recommendationFixState('score', id, {packageSqs: undefined});\n"
        # a card that now asks for the same value hides the row - it is still open, never fixed
        "const grouped = {warnings: {required: [{cluster: 'c', count: 1, items: [{message: 'm', resolution: {mode: 'field', facts: ['distance_to_hydrant']}}]}]}};\n"
        "out.hiddenByCard = [R.buildRecommendations({packageSqs: pkg, groupedIssues: grouped}).score.some(s => s.id === id), R.recommendationFixState('score', id, {packageSqs: pkg})];\n"
        "out.dryListed = R.recommendationFixState('dry', 'b1', {dryRun: dry([{id: 'b1'}]), formId: 'ACORD_140'});\n"
        "out.dryFixed = R.recommendationFixState('dry', 'b1', {dryRun: dry([{id: 'b2'}]), formId: 'ACORD_140'});\n"
        "out.dryPending = R.recommendationFixState('dry', 'b1', {dryRun: dry([], ['ACORD_140'], 'pending'), formId: 'ACORD_140'});\n"
        "out.dryOtherForms = R.recommendationFixState('dry', 'b1', {dryRun: dry([], ['ACORD_125']), formId: 'ACORD_140'});\n"
        "out.noId = R.recommendationFixState('score', null, {packageSqs: pkg});\n"
        "console.log(JSON.stringify(out));"))
    assert o["stillAsked"] == "open" and o["gone"] == "fixed" and o["noPackage"] == "unknown"
    assert o["hiddenByCard"] == [False, "open"]
    assert o["dryListed"] == "open" and o["dryFixed"] == "fixed"
    assert o["dryPending"] == "unknown" and o["dryOtherForms"] == "unknown"
    assert o["noId"] == "unknown"


@pytest.mark.skipif(_NODE, reason="node is not installed")
def test_the_resolved_rows_and_their_page(tmp_path):
    o = _node(tmp_path, {"R": _REC, "V": _RESOLVED}, (
        "const st = (status, message, extra = {}) => ({status, message, form_id: null, ...extra});\n"
        "const entries = [\n"
        "  ['rec:score:property_integrity:fact:distance_to_hydrant', st('resolved', 'Property Integrity: hydrant', {severity: 'recommendation'})],\n"
        "  ['rec:dry:ACORD_140_field_year_built', st('resolved', 'ACORD 140: Year built', {form_id: 'ACORD_140'})],\n"
        "  ['rec:score:narrative_quality:fact:additional_remarks_text', st('resolved', 'Narrative Quality: x')],\n"
        "  ['rec:score:loss_history_alignment:fact:x', st('open', 'Loss')],\n"
        "  ['rec:score:exposure_consistency:fact:y', st('resolved', '')],\n"
        "  ['iss_abc', st('resolved', 'A warning', {severity: 'warning'})],\n"
        "];\n"
        "const live = new Set(['rec:score:narrative_quality:fact:additional_remarks_text']);\n"
        "const choices = [{id: 'c1', asked: ['ACORD_186'], forms: [], done: true, message: 'contractor'}, {id: 'c2', asked: ['ACORD_25'], forms: ['ACORD_25'], done: false}];\n"
        "const rows = R.recommendationResolvedRows({statusEntries: entries, liveIds: live, formChoices: choices});\n"
        "console.log(JSON.stringify({\n"
        "  rows: rows.map(r => [r.iid, r.kind, r.status, r.forms]),\n"
        # a recommendation is never filed under Warnings, even with no page stored
        "  warn: V.storedHandledRows(entries, {liveIds: new Set(), page: 'warning'}).map(r => r.iid),\n"
        "  rec: V.storedHandledRows(entries, {liveIds: new Set(), page: 'recommendation'}).map(r => r.iid),\n"
        "  pages: [V.pageOfStatus({severity: 'recommendation'}), V.pageOfStatus({}, 'rec:dry:x'), V.pageOfStatus({severity: 'hard'}), V.pageOfStatus(null)],\n"
        "  ids: [V.recScoreIssueId('score:p:k'), V.recDryIssueId('d1'), V.recChoiceIssueId('c1'), V.recScoreIssueId(null), V.isRecommendationId('iss_1')],\n"
        "}));"))
    assert o["rows"] == [
        ["rec:score:property_integrity:fact:distance_to_hydrant", "score", "resolved", []],
        ["rec:dry:ACORD_140_field_year_built", "dry", "resolved", ["ACORD_140"]],
        ["rec:choice:c1", "choice", "added", ["ACORD_186"]],
    ]
    assert o["warn"] == ["iss_abc"]
    assert "iss_abc" not in o["rec"] and "rec:dry:ACORD_140_field_year_built" in o["rec"]
    assert o["pages"] == ["recommendation", "recommendation", "hard", "warning"]
    assert o["ids"] == ["rec:score:p:k", "rec:dry:d1", "rec:choice:c1", None, False]


def test_the_screens_wire_it_through_the_one_reopen_door():
    modal = (_FRONT / "components" / "form" / "AcordModal.jsx").read_text(encoding="utf-8")
    rail = (_FRONT / "components" / "form" / "review" / "ReviewRailLayout.jsx").read_text(encoding="utf-8")
    recs = (_FRONT / "components" / "form" / "review" / "Recommendations.jsx").read_text(encoding="utf-8")
    dry = (_FRONT / "utils" / "dryRun.js").read_text(encoding="utf-8")
    # a fix from a row's window carries the row's id, so the server files the receipt under it
    assert "issue_id: recDryIssueId(item?.id)," in dry
    # judged on save; a check still running is judged when it finishes
    assert "try { markRecommendationFix(data, issue); }" in modal
    assert 'recommendationFixState("dry", p.itemId, { dryRun, formId: p.meta.form_id })' in modal
    # "Open again" is the one reopen door; never optimistic (the row stays put until the server answers)
    assert 'handleReopenIssue(row.iid, "open", {' in modal and "severity: REC_PAGE," in modal
    # the editor's Cross-Form Resolved list never shows a recommendation
    assert "&& pageOfStatus(st, iid) !== REC_PAGE)" in modal
    # both layouts render it
    assert "onReopenResolved={onReopenRecommendation}" in rail
    assert "onReopenResolved={reopenRecommendation}" in modal
    assert "<ResolvedGroup rows={resolved} onReopen={onReopenResolved}" in recs
    for text in (rail, recs):                       # no em-dashes in UI text (AcordModal comments carry old ones)
        assert "—" not in text


def test_every_recommendations_group_folds_like_hard_stops_and_warnings():
    """Owner, 13 Oct 2026: "add a little drop down icon like warnings and hard stops on
    recommendations as well". Each group's heading is a fold with the same small triangle;
    the working groups start open, Resolved starts closed, and a folded form check stays
    mounted (it keeps polling and re-checking on the ticks)."""
    recs = (_FRONT / "components" / "form" / "review" / "Recommendations.jsx").read_text(encoding="utf-8")
    css = (_FRONT / "components" / "form" / "review" / "Recommendations.css").read_text(encoding="utf-8")
    assert '<span className="rec-tri" aria-hidden="true">▶</span>' in recs
    assert 'aria-expanded={open} onClick={onToggle}' in recs
    for title in ('title="Raise your score"', 'title="Your forms will need"', 'title="Resolved"'):
        assert title in recs, title
    assert "const [open, setOpen] = useState(true);" in recs            # Raise your score: open
    assert "const [groupOpen, setGroupOpen] = useState(true);" in recs  # after forms: open
    resolved = recs[recs.index("function ResolvedGroup"):recs.index("function AfterFormsGroup")]
    assert "useState(false)" in resolved                                # Resolved: closed
    # 14 Oct 2026 (owner): no forms group before forms at all.
    assert "formsOpen" not in recs and "<BeforeYouGenerate" not in recs
    assert '.rec-fold[aria-expanded="true"] > .rec-tri { transform: rotate(90deg); }' in css
