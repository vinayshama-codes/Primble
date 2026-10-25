"""Recommendations rows never vanish without a trace (owner, 14 Oct 2026, run 91c865a5).

The owner, on the pre-form Review -> Recommendations: "there are 4 recommendations to fix
and then i solved no loss history and 2 of the recommendations disappeared from there and
they didnt go into resolved and when i reopened it they came back and only narrative one
is left".

Replayed on the package (facts rebuilt from its documents, the owner's 13 answers through
the real routes - scores 51 55 58 61 63 65 70 / 79 / 70 / 79, exactly the live history):

  before the answer  Loss History +9, Narrative up to +5, Distance to the nearest fire
                     hydrant +1, Fire department type +1 (FEIN sits behind its key-detail
                     link). Weighted sum 70.90.
  after it           Loss History is Not Applicable, the other pillars re-weight and the
                     sum lands on 79.00. Each COPE row is worth 5 x 0.15 / 0.85 = 0.88;
                     79.88 still floors to 79 (spec: "rounded down"), so both measured an
                     answer_gain of 0 and `pointsFor` dropped them as "adds nothing" -
                     though both boxes were still empty and Property Integrity still 90.
                     "Open again" put the sum back on 70.90 (+0.75 -> 71) and they returned.

Two rules come out of it:

1. A measured 0 on a row worth under one point is the floor, not "nothing": the row stays
   listed, "up to +1 pts" (both together lift 79.00 to 80.76). A pillar at 0 is still the
   exception (the COPE minimum is missing - nothing in it counts yet), and a row worth a
   point or more that measures 0 still adds nothing now.
2. A row another fix DID answer goes to Resolved, "Cleared by your answer to <row>", and
   its "Open again" takes that answer back. The same run had one: the COPE card's location
   table filled year built, roof year, sprinkler and protection class - four listed rows
   left with no record. The hard stop / warning pages already file what a save clears
   (`resolvedIssues.clearedBlockers`); the Recommendations page now does too.
   (21 Oct 2026, Brent 17 Oct item 8: on 2+ buildings those four rows open the same
   location-table cells as the card, so they are no longer listed beside it - one to-do,
   one place. The rule stands for every other row a fix answers.)

The route tests drive the REAL resolve / reopen routes and scorer through the in-memory
session of tests/test_reopen_takes_the_fix_back_9oct.py; the frontend rules run under node.
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

import test_reopen_takes_the_fix_back_9oct as H                                    # noqa: E402
from test_reopen_takes_the_fix_back_9oct import _Session, _mdY, _producer, _row  # noqa: E402

import services.issue_fix_undo as undo                                           # noqa: E402

_FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"
_REC = _FRONT / "utils" / "recommendations.js"
_RESOLVED = _FRONT / "utils" / "resolvedIssues.js"
_NODE = shutil.which("node") is None
_LOSS = "loss_history_no_prior_losses_indicator"
_LOSS_ID = f"score:loss_history_alignment:fact:{_LOSS}"


def _node(tmp_path, imports: dict, body: str) -> dict:
    head = "".join(f"import * as {name} from {json.dumps(path.as_uri())};\n" for name, path in imports.items())
    script = tmp_path / "check.mjs"
    script.write_text(head + body + "\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


# ══ The live shape of 91c865a5 (the rows as the scorer sent them; no PII) ════
def _r(pillar, field, score, pts, gain=None, mode="field", action=None, **extra):
    row = {"pillar": pillar, "field": field, "score": score, "points_available": pts,
           "answer_mode": mode, "action": action or field, "missing": [action or field],
           "closes_with": "type",
           "resolution": ({"mode": "narrative"} if mode == "narrative"
                          else {"mode": "field", "facts": [field]})}
    if gain is not None:
        row["answer_gain"], row["answer_gain_is_exact"] = gain, True
    row.update(extra)
    return row


_HYDRANT, _FIRE = "Distance to the nearest fire hydrant", "Fire department type"
_NO_LOSS_ROW = "No loss history provided - required for carrier submission"
_NARR = "Narrative includes Operations Description, but does not include Account Overview"
# Weighted sum 70.90 -> 70: each COPE row (+0.75) measures +1.
_LIVE_BEFORE = {"package_sqs_score": 70, "top_recommendations": [
    _r("structural_completeness", "fein", 53, 11.8, 2, action="FEIN / Tax ID"),
    _r("loss_history_alignment", _LOSS, 25, 11.2, 9, action=_NO_LOSS_ROW),
    _r("narrative_quality", "additional_remarks_text", 54, 4.6, mode="narrative", action=_NARR),
    _r("property_integrity", "distance_to_hydrant", 90, 0.8, 1, action=_HYDRANT),
    _r("property_integrity", "fire_department_type", 90, 0.8, 1, action=_FIRE),
]}
# After "No known losses": Loss History N/A, sum 79.00 -> 79; each COPE row (+0.88)
# measures 0. These are the stored package's own rows (answer_gain 0, points 0.9).
_LIVE_AFTER = {"package_sqs_score": 79, "top_recommendations": [
    _r("structural_completeness", "fein", 53, 13.8, 2, action="FEIN / Tax ID"),
    _r("narrative_quality", "additional_remarks_text", 54, 5.4, mode="narrative", action=_NARR),
    _r("property_integrity", "distance_to_hydrant", 90, 0.9, 0, action=_HYDRANT),
    _r("property_integrity", "fire_department_type", 90, 0.9, 0, action=_FIRE),
]}
# FEIN is answered from its "Key details missing" link, so its score row is not repeated.
_KEY_DETAILS = {"missing": ["FEIN / Tax ID"], "missing_items": [
    {"label": "FEIN / Tax ID", "resolution": {"mode": "field", "facts": ["fein"]}}]}


@pytest.mark.skipif(_NODE, reason="node is not installed")
def test_the_owners_run_keeps_the_two_cope_rows_listed(tmp_path):
    o = _node(tmp_path, {"R": _REC}, (
        f"const before = {json.dumps(_LIVE_BEFORE)};\n"
        f"const after = {json.dumps(_LIVE_AFTER)};\n"
        f"const kd = {json.dumps(_KEY_DETAILS)};\n"
        "const show = (pkg) => R.buildRecommendations({packageSqs: pkg, keyDetails: kd}).score.map(s => [s.detail, R.pointsText(s.points)]);\n"
        "const listed = R.buildRecommendations({packageSqs: before, keyDetails: kd}).score;\n"
        "console.log(JSON.stringify({\n"
        "  before: show(before), after: show(after),\n"
        # the loss row is the save's own; nothing else was answered, so nothing is filed
        f"  cleared: R.clearedScoreItems(listed, after, new Set([{json.dumps(_LOSS_ID)}])).map(s => s.id),\n"
        "}));"))
    assert o["before"] == [[_NO_LOSS_ROW, "+9 pts"], [_NARR, "up to +5 pts"],
                           [_HYDRANT, "+1 pts"], [_FIRE, "+1 pts"]]
    # Was: [[narrative, "up to +5 pts"]] - the two COPE rows vanished.
    assert o["after"] == [[_NARR, "up to +5 pts"], [_HYDRANT, "up to +1 pts"], [_FIRE, "up to +1 pts"]]
    # Still missing is never "Resolved": the two rows were not answered by anything.
    assert o["cleared"] == []


@pytest.mark.skipif(_NODE, reason="node is not installed")
def test_what_a_measured_zero_means(tmp_path):
    o = _node(tmp_path, {"R": _REC}, (
        "const row = (extra) => ({pillar: 'property_integrity', field: 'x', answer_mode: 'field', action: 'a', ...extra});\n"
        "const p = (extra) => R.pointsText(R.pointsFor(row(extra)));\n"
        "console.log(JSON.stringify({\n"
        # under a point, pillar above 0: the floor - listed as a bound
        "  floor: p({answer_gain: 0, answer_gain_is_exact: true, points_available: 0.9, score: 90}),\n"
        "  small: p({answer_gain: 0, answer_gain_is_exact: true, points_available: 0.3, score: 90}),\n"
        "  noScore: p({answer_gain: 0, answer_gain_is_exact: true, points_available: 0.8}),\n"
        # a pillar at 0: the COPE minimum is missing, nothing in it counts yet
        "  gated: p({answer_gain: 0, answer_gain_is_exact: true, points_available: 0.8, score: 0}),\n"
        # worth a point or more and measures 0: it adds nothing now
        "  worthMore: p({answer_gain: 0, answer_gain_is_exact: true, points_available: 9, score: 25}),\n"
        "  exactlyOne: p({answer_gain: 0, answer_gain_is_exact: true, points_available: 1, score: 90}),\n"
        "  noGap: p({answer_gain: 0, answer_gain_is_exact: true, points_available: 0, score: 90}),\n"
        "  noBound: p({answer_gain: 0, answer_gain_is_exact: true, score: 90}),\n"
        "  negative: p({answer_gain: -1, answer_gain_is_exact: true, points_available: 0.9, score: 90}),\n"
        # unchanged: a measured gain, an unmeasured bound
        "  gain: p({answer_gain: 1, answer_gain_is_exact: true, points_available: 0.8, score: 90}),\n"
        "  bound: p({points_available: 0.8, score: 0}),\n"
        "  tinyBound: p({points_available: 0.3, score: 90}),\n"
        "}));"))
    assert o["floor"] == "up to +1 pts" and o["small"] == "up to +1 pts" and o["noScore"] == "up to +1 pts"
    assert o["gated"] == "" and o["worthMore"] == "" and o["exactlyOne"] == ""
    assert o["noGap"] == "" and o["noBound"] == "" and o["negative"] == ""
    # 15 Oct 2026 (owner): a gap under half a point is listed too - a package must
    # not sit at 99 with nothing to add; the list's 100 cap keeps it honest.
    assert o["gain"] == "+1 pts" and o["bound"] == "up to +1 pts" and o["tinyBound"] == "up to +1 pts"


# ══ Rows another fix cleared ═════════════════════════════════════════════════
@pytest.mark.skipif(_NODE, reason="node is not installed")
def test_which_rows_a_save_cleared(tmp_path):
    o = _node(tmp_path, {"R": _REC}, (
        "const row = (p, f, extra = {}) => ({pillar: p, field: f, answer_mode: 'field', action: f, missing: [f], score: 50, points_available: 3, ...extra});\n"
        "const sched = (p, sk, cols, extra = {}) => ({pillar: p, field: sk, answer_mode: 'schedule', action: sk + ':' + cols.join(','), score: 50, points_available: 3,\n"
        "  resolution: {mode: 'schedule', schedule_key: sk, columns: cols}, ...extra});\n"
        "const listed = (rows) => R.scoreItems({top_recommendations: rows});\n"
        "const ids = (items) => items.map(s => s.id);\n"
        "const before = [row('loss_history_alignment', 'own'), row('loss_history_alignment', 'runs'), row('property_integrity', 'year_built'),\n"
        "  sched('exposure_consistency', 't', ['a', 'b']), sched('exposure_consistency', 'u', ['c']), row('narrative_quality', 'n')];\n"
        "const L = listed(before);\n"
        "const own = new Set([L[0].id]);\n"
        "const out = {};\n"
        # the pillar went Not Applicable: its other row is cleared; the save's own row is the window's
        "out.pillarGone = ids(R.clearedScoreItems(L, {top_recommendations: [before[2], before[3], before[4], before[5]]}, own));\n"
        # a row still asked for is never cleared: hidden by a card, part-fixed, or worth nothing now
        "out.coveredOrZero = ids(R.clearedScoreItems(L, {top_recommendations: [before[1], before[2], before[3], before[4], {...before[5], answer_gain: 0, answer_gain_is_exact: true, points_available: 9}]}, own));\n"
        "out.partFixed = ids(R.clearedScoreItems(L, {top_recommendations: [before[1], before[2], sched('exposure_consistency', 't', ['b']), before[4], before[5]]}, own));\n"
        "out.wholeTable = ids(R.clearedScoreItems(L, {top_recommendations: [before[1], before[2], sched('exposure_consistency', 't', []), before[4], before[5]]}, own));\n"
        "out.cellLeft = ids(R.clearedScoreItems(listed([sched('e', 'v', [])]), {top_recommendations: [sched('e', 'v', ['x'])]}));\n"
        # one row per pillar shows its FIRST gap: a new first gap is not an answer to the old one
        "const s1 = row('structural_completeness', 'fein', {action: 'FEIN / Tax ID'});\n"
        "const s2 = row('structural_completeness', 'mailing_address', {action: 'Applicant mailing address', missing: ['Applicant mailing address', 'FEIN / Tax ID']});\n"
        "out.reordered = ids(R.clearedScoreItems(listed([s1]), {top_recommendations: [s2]}));\n"
        "out.breakdown = ids(R.clearedScoreItems(listed([s1]), {top_recommendations: [], category_breakdown: {structural_completeness: {tier2: {missing: ['FEIN / Tax ID']}}}}));\n"
        "out.answered = ids(R.clearedScoreItems(listed([s1]), {top_recommendations: [], category_breakdown: {structural_completeness: {tier2: {missing: []}}}}));\n"
        # no new score: nothing is known, nothing is filed; the fill row is never a scorer row
        "out.noAfter = [R.clearedScoreItems(L, null).length, R.clearedScoreItems(L, undefined).length];\n"
        "out.fill = ids(R.clearedScoreItems([{id: 'score:fill', kind: 'score', pillar: 'structural_completeness', keys: ['forms:verify'], detail: 'x'}], {top_recommendations: []}));\n"
        "out.empty = [R.clearedScoreItems([], {top_recommendations: []}).length, R.clearedScoreItems(null, {}).length];\n"
        "console.log(JSON.stringify(out));"))
    assert o["pillarGone"] == ["score:loss_history_alignment:fact:runs"]
    assert o["coveredOrZero"] == []
    assert o["partFixed"] == []
    assert o["wholeTable"] == []
    assert o["cellLeft"] == []
    assert o["reordered"] == [] and o["breakdown"] == []
    assert o["answered"] == ["score:structural_completeness:fact:fein"]
    assert o["noAfter"] == [0, 0] and o["fill"] == [] and o["empty"] == [0, 0]


@pytest.mark.skipif(_NODE, reason="node is not installed")
def test_the_status_says_which_answer_cleared_it(tmp_path):
    o = _node(tmp_path, {"R": _REC, "V": _RESOLVED}, (
        "const out = {};\n"
        "out.reason = [V.clearedByReason('Loss History: No loss history provided.'), V.clearedByReason(' '), V.clearedByReason(null)];\n"
        "out.read = [V.clearedByOf({reason: out.reason[0], rule_code: 'rec:score:loss'}), V.clearedByOf({reason: out.reason[0], rule_code: ''}),\n"
        # a later fix of the row in its own window rewrites the reason (the store keeps an old rule code)
        "  V.clearedByOf({reason: null, rule_code: 'rec:score:loss'}), V.clearedByOf({reason: 'Dismissed: not needed', rule_code: 'x'}), V.clearedByOf(null)];\n"
        "out.fixOf = [\n"
        "  R.clearingFixOf({__scoreItem: true, issue_id: 'rec:score:l', __recTitle: 'Loss History: No loss history provided', message: 'm'}),\n"
        "  R.clearingFixOf({message: 'Property Minimum Viable COPE incomplete - missing: occupancy type Fix: Review and correct this before proceeding.', code: 'legacy_minimum_viable_cope'}, (i) => 'iss_57ef2c1bec59'),\n"
        "  R.clearingFixOf({message: 'ACORD 125 minimum field missing: Applicant mailing address (Fix: Provide this value manually.)', issue_id: 'iss_1'}),\n"
        "  R.clearingFixOf({__keyDetail: true, issue_id: null, __keyDetailLabel: 'Years in business', message: 'Key detail missing: Years in business. x'}),\n"
        "  R.clearingFixOf(null),\n"
        "];\n"
        "out.text = [R.clearedByText({iid: 'rec:x', title: 'Loss History: No loss history provided.'}), R.clearedByText({iid: null, title: 'Years in business'}),\n"
        "  R.clearedByText({iid: 'i', title: ''}), R.clearedByText(null)];\n"
        "console.log(JSON.stringify(out));"))
    assert o["reason"] == ["Cleared by your answer to Loss History: No loss history provided.", "", ""]
    assert o["read"] == [{"iid": "rec:score:loss", "title": "Loss History: No loss history provided"},
                         {"iid": None, "title": "Loss History: No loss history provided"},
                         None, None, None]
    assert o["fixOf"] == [
        {"iid": "rec:score:l", "title": "Loss History: No loss history provided"},
        {"iid": "iss_57ef2c1bec59", "title": "Property Minimum Viable COPE incomplete - missing: occupancy type"},
        {"iid": "iss_1", "title": "ACORD 125 minimum field missing: Applicant mailing address"},
        {"iid": None, "title": "Years in business"},
        {"iid": None, "title": ""},
    ]
    assert o["text"] == [
        "Cleared by your answer to Loss History: No loss history provided. Open again takes that answer back.",
        "Cleared by your answer to Years in business.",
        "Cleared by your answer to another item. Open again takes that answer back.",
        "",
    ]
    for t in o["text"]:
        assert "—" not in t                                   # no em-dashes in UI text


@pytest.mark.skipif(_NODE, reason="node is not installed")
def test_resolved_rows_and_what_open_again_reopens(tmp_path):
    o = _node(tmp_path, {"R": _REC, "V": _RESOLVED}, (
        "const by = (title, iid) => ({reason: V.clearedByReason(title), rule_code: iid});\n"
        "const st = (status, message, extra = {}) => ({status, message, form_id: null, severity: 'recommendation', ...extra});\n"
        "const LOSS = 'rec:score:loss_history_alignment:fact:loss';\n"
        "const entries = [\n"
        "  [LOSS, st('resolved', 'Loss History: No loss history provided')],\n"
        "  ['rec:score:loss_history_alignment:fact:runs', st('resolved', 'Loss History: Loss runs', by('Loss History: No loss history provided', LOSS))],\n"
        "  ['rec:score:property_integrity:fact:year_built', st('resolved', 'Property Integrity: Year built', by('Carrier-Grade COPE incomplete', 'iss_cope'))],\n"
        "  ['rec:score:structural_completeness:fact:naics_code', st('resolved', 'Structural Completeness: NAICS', by('Years in business', ''))],\n"
        "  ['iss_cope', {status: 'open', message: 'Carrier-Grade COPE incomplete', rule_code: 'legacy_carrier_grade_cope', severity: 'warning', form_id: null}],\n"
        "  ['rec:score:narrative_quality:fact:n', st('resolved', 'Narrative', by('Loss History: No loss history provided', LOSS))],\n"
        "];\n"
        "const live = new Set(['rec:score:narrative_quality:fact:n']);\n"
        "const rows = R.recommendationResolvedRows({statusEntries: entries, liveIds: live});\n"
        "const statusOf = (iid) => (entries.find(([i]) => i === iid) || [null, null])[1];\n"
        "console.log(JSON.stringify({\n"
        "  rows: rows.map(r => [r.iid, r.clearedBy]),\n"
        "  targets: rows.map(r => R.recommendationReopenTarget(r, statusOf)),\n"
        "  choice: R.recommendationReopenTarget({iid: 'rec:choice:c', kind: 'choice'}),\n"
        "  none: R.recommendationReopenTarget(null),\n"
        "  linked: [V.rowsClearedBy(entries, LOSS), V.rowsClearedBy(entries, 'iss_cope'), V.rowsClearedBy(entries, null)],\n"
        "}));"))
    assert o["rows"] == [
        ["rec:score:loss_history_alignment:fact:loss", None],
        ["rec:score:loss_history_alignment:fact:runs",
         {"iid": "rec:score:loss_history_alignment:fact:loss", "title": "Loss History: No loss history provided"}],
        ["rec:score:property_integrity:fact:year_built", {"iid": "iss_cope", "title": "Carrier-Grade COPE incomplete"}],
        ["rec:score:structural_completeness:fact:naics_code", {"iid": None, "title": "Years in business"}],
    ]
    loss_meta = {"form_id": None, "rule_code": None, "message": "Loss History: No loss history provided",
                 "severity": "recommendation"}
    assert o["targets"] == [
        {"iid": "rec:score:loss_history_alignment:fact:loss", "meta": loss_meta},         # its own fix
        {"iid": "rec:score:loss_history_alignment:fact:loss", "meta": loss_meta},         # the fix that cleared it
        {"iid": "iss_cope", "meta": {"form_id": None, "rule_code": "legacy_carrier_grade_cope",
                                     "message": "Carrier-Grade COPE incomplete", "severity": "warning"}},
        None,                                                       # a key detail: nothing on file to take back
    ]
    assert o["choice"] is None and o["none"] is None
    assert o["linked"] == [["rec:score:loss_history_alignment:fact:runs", "rec:score:narrative_quality:fact:n"],
                           ["rec:score:property_integrity:fact:year_built"], []]


# ══ End to end: the real routes and scorer, the frontend's rules ═════════════
_ROWS = [{"address_line1": "100 Main St", "address_city": "Denver", "address_state": "CO",
          "address_zip": "80202", "location_number": "1", "building_number": str(n),
          "construction_type": "Frame", "building_value": value, "bpp_value": "100000"}
         for n, value in ((1, "500000"), (2, "300000"))]
_COPE_COLUMNS = {"year_built": "1999", "roof_year": "2015", "sprinkler": "100", "protection_class": "3"}
# On 2+ buildings each COPE row opens the location table with its column (21 Oct 2026,
# Brent 17 Oct item 8 - one store for building details); its id stays keyed on its fact.
_COPE_FACTS = ("year_built", "roof_year", "sprinkler_system", "fire_protection_class")
_COPE_ROWS = [f"score:property_integrity:fact:{f}" for f in _COPE_FACTS]


async def _noop(*_a, **_k):
    return None


def _two_building_package():
    """Two buildings, Minimum Viable COPE in place, the four carrier-grade COPE values and the
    hydrant / fire department missing - the shape of 91c865a5 after its occupancy answer."""
    row = _row(generated_forms={}, selected_form_ids=[])
    row["facts"]["effective_date"] = _producer(_mdY(datetime.now() - timedelta(days=165)))
    row["facts"]["expiration_date"] = _producer(_mdY(datetime.now() + timedelta(days=200)))
    row["flags"]["has_property_coverage"] = True
    row["facts"].update({"property_locations": copy.deepcopy(_ROWS), "locations": copy.deepcopy(_ROWS),
                         "occupancy_type": "Office", "construction_type": "Frame",
                         "property_building_value": "500000", "business_income_limit": "$100,000",
                         "period_of_restoration": "12 months"})
    s = _Session(row)
    import routes.form_routes as fr
    with patch.object(fr, "_pre_form_dry_run", _noop):
        s.recalc()
    return s


def _screen(s) -> dict:
    """GET /extraction-result - the Review screen as a reload draws it."""
    import routes.form_routes as fr

    async def _go():
        return await fr.get_extraction_result(H._SID, {"id": H._UID, "payment_status": "ok"})
    with patch.object(fr, "get_processing_session", s._get), \
         patch.object(fr, "upd_processing_session", s._upd), \
         patch.object(fr, "sync_recommendation_cards", _noop), \
         patch.object(fr, "log_field_change", _noop), \
         patch.object(fr, "_pre_form_dry_run", _noop):
        body = json.loads(s.run(_go).body)
    return {k: body.get(k) for k in ("package_sqs", "grouped_issues", "key_details")}


def _payload(body: dict) -> dict:
    return {k: body.get(k) for k in ("package_sqs", "grouped_issues", "key_details")}


def _card(screen: dict, code: str) -> dict:
    for tier in ((screen.get("grouped_issues") or {}).get("warnings") or {}).values():
        for c in tier or []:
            for it in c.get("items") or [c]:
                if it.get("code") == code:
                    return it
    raise AssertionError(f"{code} not on screen")


@pytest.mark.skipif(_NODE, reason="node is not installed")
def test_the_cope_card_asks_each_building_once_and_open_again_takes_it_back(tmp_path):
    # REWRITTEN 21 Oct 2026 (Brent 17 Oct item 8, b-cope-one-store). This was
    # "a card fix that answers score rows files them": the four COPE rows were
    # listed BESIDE the COPE card that asks the same building cells - one row per
    # package value, the card per building - and the card's save filed them as
    # "Cleared by your answer to ...". That was Brent's "asked twice"; the TEST
    # pinned it. Now each row opens the same location-table cells as the card,
    # so it is not repeated beside it (one to-do, one place) and nothing is left
    # to clear. Rule 2 itself (a row another fix answered goes to Resolved) is
    # unchanged and pinned by the static tests above.
    import routes.audit_routes as ar
    import routes.form_routes as fr
    from models.schemas import ResolveIssueRequest, ReopenIssueRequest

    s = _two_building_package()
    before_score = s.score()
    before = _screen(s)
    card = _card(before, "legacy_carrier_grade_cope")
    assert card["resolution"]["mode"] == "schedule"           # 2+ buildings: the card opens the table
    assert card["resolution"]["columns"] == list(_COPE_COLUMNS)   # the four it still misses

    # The COPE card's window saves the location table with the four columns filled.
    rows = [{**r, **_COPE_COLUMNS} for r in copy.deepcopy(_ROWS)]
    with patch.object(fr, "_pre_form_dry_run", _noop):
        out = s.body(ar.resolve_issue, ResolveIssueRequest(
            session_id=H._SID, issue_id=card["issue_id"], code=card["code"], mode="schedule",
            schedule_key="property_locations", rows=rows))
    assert out["success"] is True and s.score() > before_score
    assert card["issue_id"] in undo.load_receipts(s.store)   # the fix is on file under the card

    o = _node(tmp_path, {"R": _REC, "V": _RESOLVED, "P": _REC.with_name("screenPoints.js")}, (
        f"const before = {json.dumps(before)};\n"
        f"const after = {json.dumps(_payload(out))};\n"
        f"const card = {json.dumps(card)};\n"
        "const model = (sc) => R.buildRecommendations({packageSqs: sc.package_sqs, groupedIssues: sc.grouped_issues, keyDetails: sc.key_details});\n"
        "const listed = model(before).score;\n"
        "console.log(JSON.stringify({\n"
        "  listed: listed.map(s => [s.id, R.pointsText(s.points)]),\n"
        "  asked: R.scoreItems(before.package_sqs, new Set()).map(s => s.id),\n"
        "  after: model(after).score.map(s => s.id),\n"
        "  afterAsked: R.scoreItems(after.package_sqs, new Set()).map(s => s.id),\n"
        "  cleared: R.clearedScoreItems(listed, after.package_sqs).map(s => s.id),\n"
        "  cardPoints: (P.screenPoints(before.package_sqs, before.grouped_issues, before.key_details).cards.get(card.code) || {}).points || 0,\n"
        "}));"))
    listed = dict(o["listed"])
    for rid in _COPE_ROWS:
        assert rid in o["asked"]                 # the score still asks each of the four...
        assert rid not in listed                 # ...once: on the card that opens those cells
    # The hydrant / fire department rows are listed, never dropped. Location-wide: typed
    # boxes, never the table. Since the page-wide plan (24 Oct 2026) each says what it
    # adds after the items above it - here the 85 the COPE warning keeps (its table
    # leaves valuation method and coinsurance) withholds them, and they say so.
    for fact in ("distance_to_hydrant", "fire_department_type"):
        text = listed[f"score:property_integrity:fact:{fact}"]
        assert text.startswith("Counts once ") or text.endswith(" pts"), text
    # The table answered the four: asked nowhere any more; the rest still listed.
    assert not set(_COPE_ROWS) & set(o["afterAsked"])
    assert not set(_COPE_ROWS) & set(o["after"])
    assert "score:property_integrity:fact:distance_to_hydrant" in o["after"]   # not answered, still listed
    assert o["cleared"] == []                    # nothing listed was answered by another fix
    # The four rows' points are not lost with them: they print on the card that asks them
    # (the page-wide plan, 24 Oct 2026: a fix offered twice counts at its first place -
    # the card - and each row mirrors it, adding nothing to the total).
    items = {i["id"]: i for i in (before["package_sqs"].get("review_plan") or {}).get("items") or []}
    card_item = items[f"card:{card['code']}"]
    rows = [i for i in items.values() if i["kind"] == "rec"
            and i.get("field") in _COPE_FACTS]
    assert card_item["points"] > 0 and o["cardPoints"] == card_item["points"]
    assert rows and all(i["points"] == 0 and i.get("mirror_of") == card_item["id"] for i in rows)

    # "Open again" on the card: the one reopen door takes the four back with their points.
    with patch.object(fr, "_pre_form_dry_run", _noop):
        back = s.body(ar.reopen_issue, ReopenIssueRequest(
            session_id=H._SID, issue_id=card["issue_id"], code=card["code"], message=card["message"]))
    assert back["cleared"] is True
    assert s.score() == before_score                             # the points came off again
    o2 = _node(tmp_path, {"R": _REC, "V": _RESOLVED}, (
        f"const back = {json.dumps(_payload(back))};\n"
        f"const ids = {json.dumps([f'rec:{rid}' for rid in _COPE_ROWS])};\n"
        "const live = R.liveRecommendationIds({packageSqs: back.package_sqs});\n"
        "const model = R.buildRecommendations({packageSqs: back.package_sqs, groupedIssues: back.grouped_issues, keyDetails: back.key_details});\n"
        "console.log(JSON.stringify({live: ids.map(i => live.has(i)), listed: ids.map(i => model.score.some(s => V.recScoreIssueId(s.id) === i))}));"))
    assert o2["live"] == [True] * 4                  # asked again...
    assert o2["listed"] == [False] * 4               # ...by the card, once


def test_the_screens_wire_it_through():
    modal = (_FRONT / "components" / "form" / "AcordModal.jsx").read_text(encoding="utf-8")
    recs = (_FRONT / "components" / "form" / "review" / "Recommendations.jsx").read_text(encoding="utf-8")
    # every save files the rows it cleared besides its own, against the list on screen
    assert "markClearedBlockers(data, issue);\n    markClearedRecommendations(data, issue);" in modal
    assert "scoreItems(packageSqs, onScreenFixKeys(groupedIssues, keyDetails))" in modal
    assert "reason: clearedByReason(by.title" in modal and 'rule_code: by.iid || "",' in modal
    # the reason reaches the store (it was never sent before)
    assert "reason:      meta.reason      ?? null," in modal
    # "Open again" reopens the clearing fix through the one door, never optimistic
    assert "recommendationReopenTarget(row, (iid) => issueStatuses.get(iid) || null)" in modal
    assert 'handleReopenIssue(target.iid, "open", target.meta, { optimistic: false });' in modal
    # a fix taken back puts the rows it cleared back in their list
    assert "reopenRowsClearedBy(issueId, data);" in modal
    # a key detail names itself on the rows it clears
    assert "__keyDetailLabel: item.label || null," in modal
    # the row says what cleared it; a key-detail clear offers no "Open again"
    assert "positiveScoreWording(clearedByText(by))" in recs
    assert 'typeof onReopen === "function" && (!by || !!by.iid)' in recs
    assert "—" not in recs
