"""Reach 100 AFTER forms too (owner, 29 Oct 2026: "the points shown on items always
add up to exactly 100 - score, AFTER forms are generated too (the side panel /
editor), exactly as they already do on the pre-form review page; solving
everything the panel shows must reach exactly 100, never hang at 98").

The reviewer's finding: `_complete_screen_shares_plan` returned early once forms
existed, so the editor's side panel printed the scorer's own row shares - on
Orbin 432c8594 (4 forms) the rows read +2 +1 +1 +2 +6 +3 = 15 at 79, six points
on no item, while the same facts before forms listed ten items adding to exactly
100. The plan is now weighed after forms too (the post-generation stops, the
stored credit-bearing score) and read by the side panel through
`GET /api/session/{id}/screen-points` (`form_routes.screen_points_after_forms`).

Synthetic packages shaped like the three stored ones (Orbin: 4 forms; Choice
Electric: 11 forms with an excess 131; CH125: 3 forms) - no customer data, no
model or network call.
"""
import asyncio
import copy
import json
import logging
import os
import random
import shutil
import subprocess

import pytest

import reach100_harness as H
from services import review_plan as RP
from services import sqs_service as S

_SHAPES = {
    # seed -> the forms the package generated (the stored session's shape)
    "orbin": (38, ["ACORD_125", "ACORD_126", "ACORD_127", "ACORD_131"]),
    "choice_electric": (14, ["ACORD_101", "ACORD_125", "ACORD_126", "ACORD_127", "ACORD_130",
                             "ACORD_131", "ACORD_131__excess", "ACORD_137_CO", "ACORD_140",
                             "ACORD_141", "ACORD_28"]),
    "ch125": (31, ["ACORD_125", "ACORD_126", "ACORD_127"]),
}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("no model or network call")
    import httpx
    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setenv("NARRATIVE_READER", "0")
    monkeypatch.setenv("EVIDENCE_JUDGE", "0")
    monkeypatch.setenv("CARRIER_NARRATIVE", "0")
    # The real recalculation's audit writes have no database here; they fail
    # quietly by design - keep the log readable.
    logging.getLogger("services.audit_service").setLevel(logging.CRITICAL)


# ── The package after forms ─────────────────────────────────────────────────
def _generated(fids):
    return {f: {"form_id": f, "form_name": f, "sqs": {"form_id": f, "sqs_score": 80}} for f in fids}


def _rescore(row: dict, credits: int = 0) -> dict:
    """The stored package score as `arq_service.recalculate_session_scores`
    leaves it after forms: the post-generation stops, the package scorer, a
    credit added to the raw score."""
    from services.stops_now import stops_now
    st = stops_now(row, None, pre_form=False)
    sqs_list = [f["sqs"] for f in (row.get("generated_forms") or {}).values()]
    pkg = S.calculate_package_sqs(
        facts=row["facts"], flags=row.get("flags") or {}, form_results=sqs_list,
        cross_issues=st["cross_issues"], hard_stops=st["hard"], soft_stops=st["soft"],
        session_data=row, calculation_stage="arq_remediated")
    if credits:
        S.apply_credits_to_score(pkg, credits, None, "package_sqs_score")
    row["package_sqs"] = pkg
    return pkg


def _shape(name: str) -> dict:
    seed, fids = _SHAPES[name]
    row = H.synthetic_package(random.Random(seed))
    if name == "orbin":                      # Orbin's own gaps: three key details
        for k in ("num_employees", "years_in_business", "naics_code"):
            row["facts"].pop(k, None)
    row["selected_form_ids"] = list(fids)
    row["generated_forms"] = _generated(fids)
    row["user_id"] = "u"
    _rescore(row)
    return row


def _read(row: dict, credit_rows=None):
    from routes.form_routes import screen_points_after_forms
    out = screen_points_after_forms(row, "s", "u", credit_rows)
    pkg, kd, grouped = out["package_sqs"], out["key_details"], out["grouped_issues"]
    return pkg, kd, RP.page_items(row, pkg, kd, grouped)


# ── 1. The side panel's numbers add up to 100 - score after forms ────────────
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_the_side_panel_numbers_add_up_to_100_minus_the_score_after_forms(shape):
    row = _shape(shape)
    pkg, kd, _items = _read(row)
    score = pkg["package_sqs_score"]
    assert score < 100, "the shape must leave something to do"
    plan = pkg.get("review_plan") or {}
    assert plan.get("after_forms") is True
    assert H.plan_problems(pkg) == [], H.plan_problems(pkg)
    shown = sum(int(i.get("points") or 0) for i in plan["items"] if not i.get("mirror_of"))
    assert score + shown == 100
    # The plan's numbers are on the score's own rows and key details too.
    rows = [r for r in pkg.get("top_recommendations") or [] if r.get("plan_id")]
    assert rows and all("answer_gain" in r for r in rows)
    assert all("points" in it for it in (kd.get("missing_items") or []))


def test_orbins_shape_lists_the_key_details_the_rows_never_carried():
    """The six missing points: Orbin's employees / years / NAICS are key details,
    never Best Solutions rows - after forms the plan lists them with their points."""
    row = _shape("orbin")
    pkg, kd, _items = _read(row)
    plan = pkg["review_plan"]
    details = [i for i in plan["items"] if i["kind"] == "detail"]
    assert {"Number of employees", "Years in business"} <= {d["label"] for d in details}
    assert sum(int(d["points"]) for d in details) > 0
    # The old share-out on the rows alone does not reach 100 - the defect.
    old_rows = sum(int(r.get("answer_gain") or 0) for r in (row["package_sqs"].get("top_recommendations") or [])
                   if isinstance(r.get("answer_gain"), (int, float)) and r.get("answer_gain") > 0)
    assert row["package_sqs"]["package_sqs_score"] + old_rows < 100


# ── 2. Solving everything the panel shows reaches exactly 100 ────────────────
_STORE: dict = {}


async def _get(sid):
    return copy.deepcopy(_STORE[sid])


async def _upd(sid, updates, delete_facts=None, **_kw):
    cur = _STORE[sid]
    for k, v in (updates or {}).items():
        if k == "facts" and isinstance(v, dict):
            f = cur.setdefault("facts", {})
            for fk, fv in v.items():
                if fv is None or fv == "" or fv == [] or fv == {}:
                    continue
                f[fk] = copy.deepcopy(fv)
        else:
            cur[k] = copy.deepcopy(v)
    for k in delete_facts or []:
        cur.get("facts", {}).pop(k, None)


def _door_field(sid, field, value, same_save=None):
    """A typed answer through the route's own checks and the real door."""
    from routes.audit_routes import _term_save_refusal, _validate_producer_answer
    from services import arq_service as A
    from services.answer_routing import per_building_redirect
    ok, _err = _validate_producer_answer(field, value)
    if not ok:
        return False
    facts = _STORE[sid]["facts"]
    if _term_save_refusal(facts, field, value, same_save) or per_building_redirect(field, facts):
        return False
    applied, _ = asyncio.run(A.apply_producer_answer_to_session(sid, field, value))
    return applied


def _solve_through_the_real_doors(sid: str, rounds: int = 8):
    """Read the side panel (the screen-points door), answer every item through
    the real write doors (typed answer, table save, narrative append), re-score
    with the real recalculation after each - round after round. Returns
    (final score, every problem the panel's numbers showed)."""
    from services import arq_service as A
    from services import schedule_capture as SC
    problems = []
    for rd in range(rounds):
        row = copy.deepcopy(_STORE[sid])
        pkg, _kd, items = _read(row)
        problems += [f"r{rd}: {p}" for p in H.plan_problems(pkg)]
        if pkg.get("package_sqs_score") == 100:
            break
        probes = RP._loss_plan_probes(pkg)
        changed = False
        for it in items:
            cur = copy.deepcopy(_STORE[sid])
            res = it.get("resolution") if isinstance(it.get("resolution"), dict) else {}
            if it["kind"] == "dc":
                changed = H.confirm_conflict(_STORE[sid], it["fact"]) or changed
                continue
            if it["kind"] == "card" and res.get("mode") in (None, "none"):
                continue
            sim = RP._Sim(cur)
            before = copy.deepcopy(sim.session["facts"])
            if not RP._apply(sim, it, probes, 5):
                continue
            after = sim.session["facts"]
            if it["kind"] == "doc":
                _STORE[sid]["docs"] = sim.session["docs"]
                for k in ("loss_run_period_start", "loss_run_period_end", "loss_run_valuation_date"):
                    if k in after:
                        _STORE[sid]["facts"][k] = after[k]
                _STORE[sid]["facts"].pop("loss_run_age_days", None)
            elif res.get("mode") == "schedule" and res.get("schedule_key"):
                for f in [x for x in (res.get("facts") or []) if x]:
                    if json.dumps(after.get(f), sort_keys=True, default=str) != \
                            json.dumps(before.get(f), sort_keys=True, default=str):
                        _door_field(sid, f, str(RP._fv(after, f)))
                key = res["schedule_key"]
                ok, out = asyncio.run(A.save_session_schedule(sid, key, SC.rows_from_facts(key, after)))
                if not ok:
                    problems.append(f"r{rd}: table {key} refused: {out.get('message')}")
            elif res.get("mode") == "narrative":
                old = str(RP._fv(before, RP.NARRATIVE_FACT) or "")
                new = str(RP._fv(after, RP.NARRATIVE_FACT) or "")
                typed = new[len(old):].strip() if new.startswith(old) else new
                asyncio.run(A.append_producer_narrative(sid, typed or new))
                if it["kind"] == "card":
                    from services.issue_registry import explained_issue_codes
                    f = _STORE[sid]["facts"]
                    f["_explained_issue_codes"] = {"value": sorted(explained_issue_codes(f) | {str(it["code"])}),
                                                   "source": "producer", "confidence": "producer"}
            else:
                save = {}
                for f in [x for x in (res.get("facts") or []) if x]:
                    canon = A._canonical_key(f) or f
                    if json.dumps(after.get(canon), sort_keys=True, default=str) != \
                            json.dumps(before.get(canon), sort_keys=True, default=str):
                        save[f] = str((after.get(canon) or {}).get("answer_text") or RP._fv(after, canon))
                for f, v in save.items():
                    if not _door_field(sid, f, v, same_save=save):
                        problems.append(f"r{rd}: {f}={v!r} refused")
            changed = True
            asyncio.run(A.recalculate_session_scores(sid))
        if not changed:
            break
    pkg, _kd, _items = _read(copy.deepcopy(_STORE[sid]))
    return pkg.get("package_sqs_score"), problems


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_answering_everything_the_side_panel_shows_reaches_exactly_100(shape, monkeypatch):
    from repositories import session_repository as SR
    monkeypatch.setattr(SR, "get_processing_session", _get)
    monkeypatch.setattr(SR, "upd_processing_session", _upd)
    sid = f"pf29-{shape}"
    _STORE[sid] = _shape(shape)
    from services import arq_service as A
    asyncio.run(A.recalculate_session_scores(sid))       # the stored score, as the door leaves it
    assert _STORE[sid]["package_sqs"]["package_sqs_score"] < 100
    score, problems = _solve_through_the_real_doors(sid)
    assert score == 100 and problems == [], (score, problems)


@pytest.mark.parametrize("seed", (3, 8, 21, 28))
def test_wider_packages_after_forms_reach_100_through_the_plans_own_doors(seed):
    """`solve_checked`'s rule after forms: every reading adds up, and doing every
    item the panel lists - in reverse order too - ends at exactly 100."""
    base = H.wider_package(random.Random(seed)) if seed % 2 else H.synthetic_package(random.Random(seed))
    fids = [r["form_id"] for r in base["recommendations"]]
    for order in ("page", "reverse"):
        row = copy.deepcopy(base)
        row["selected_form_ids"], row["generated_forms"] = list(fids), _generated(fids)
        _rescore(row)
        problems = []
        for rd in range(8):
            pkg, _kd, items = _read(row)
            problems += [f"r{rd}: {p}" for p in H.plan_problems(pkg)]
            if pkg["package_sqs_score"] == 100:
                break
            sim = RP._Sim(row)
            probes = RP._loss_plan_probes(pkg)
            seq = items[::-1] if order == "reverse" else items
            changed = False
            for it in seq:
                res = it.get("resolution") if isinstance(it.get("resolution"), dict) else {}
                if it["kind"] == "dc":
                    changed = H.confirm_conflict(sim.session, it["fact"]) or changed
                elif not (it["kind"] == "card" and res.get("mode") in (None, "none")):
                    changed = RP._apply(sim, it, probes, 5) or changed
            row = sim.session
            _rescore(row)
            if not changed:
                break
        pkg, _kd, _items = _read(row)
        assert pkg["package_sqs_score"] == 100 and problems == [], (seed, order, pkg["package_sqs_score"], problems)


# ── 3. A dismissal credit counts once ───────────────────────────────────────
def test_a_dismissal_credit_is_part_of_the_score_and_retires_where_its_field_is_answered():
    row = _shape("ch125")
    plain, _kd, _ = _read(copy.deepcopy(row))
    detail = next(i for i in plain["review_plan"]["items"] if i["kind"] == "detail" and int(i["points"]) >= 2)
    field = detail["keys"][0][len("fact:"):]
    credit = [{"rec_id": "rec_test", "field": field, "score_impact": 2,
               "override_reason": "The client will send it", "message": "m"}]
    credited = copy.deepcopy(row)
    _rescore(credited, credits=2)
    assert credited["package_sqs"]["package_sqs_score"] == plain["package_sqs_score"] + 2
    pkg, _kd, _ = _read(credited, credit)
    assert H.plan_problems(pkg) == []
    assert pkg["review_plan"]["end"] == plain["review_plan"]["end"]
    item = next(i for i in pkg["review_plan"]["items"] if i["id"] == detail["id"])
    # The credit already stands in for 2 of the detail's points: the answer adds
    # only the rest, and the list still adds up to 100 minus the credited score.
    # (SCORING_RULES.md P1 / P3, 29 Oct: an item still adding a fraction shows
    # "under 1 pt" - `under` at 0 - never a point borrowed from another item.
    # TEST updated: it pinned the borrow.)
    rest = max(0, int(detail["points"]) - 2)
    assert int(item["points"]) == rest and (rest or item.get("under") or item.get("score_item") is False)
    # The simulation retires it exactly as the recalculation does.
    sim = RP._Sim(credited, credit)
    assert sim._credits() == 2
    sim.answer(field, RP.probe_value(field, sim.session["facts"], sim.session))
    assert sim._credits() == 0


def test_the_pure_credit_reader_matches_the_database_door(monkeypatch):
    from services import audit_service as AU
    rows = [{"rec_id": "a", "field": "naics_code", "score_impact": 3, "override_reason": "why"},
            {"rec_id": "b", "field": "naics_code", "score_impact": 5, "override_reason": "why"},
            {"rec_id": "c", "field": None, "score_impact": 2, "override_reason": "why"},
            {"rec_id": "d", "field": "fein", "score_impact": 4, "override_reason": "No reason provided"},
            {"rec_id": "e", "field": "total_revenue", "score_impact": 6, "override_reason": "why"}]
    facts = {"total_revenue": {"value": "1000000"}}

    async def _rows(_sid):
        return rows
    monkeypatch.setattr(AU, "get_dismissed_recommendations", _rows)
    via_db = asyncio.run(AU.active_score_credits("s", facts))
    pure = AU.credits_in_force(rows, facts, "s")
    assert via_db == pure and pure[0] == 7                     # naics 5 (largest) + fieldless 2


# ── 4. Before forms nothing changes ─────────────────────────────────────────
def test_before_forms_the_plan_is_weighed_exactly_as_it_was():
    row = H.synthetic_package(random.Random(31))
    sim = RP._Sim(row)
    assert sim.pre_form is True and sim.credit_rows == [] and sim.form_results == []
    assert sim.form_ids == [r["form_id"] for r in row["recommendations"]]
    pkg, _kd, _items = H.read_page(row)
    assert "after_forms" not in (pkg.get("review_plan") or {})
    score, problems = H.solve_checked(row)
    assert score == 100 and problems == []


def test_after_forms_the_stops_are_the_post_generation_ones():
    row = _shape("choice_electric")
    sim = RP._Sim(row)
    assert sim.pre_form is False
    assert sim.form_ids == sorted(_SHAPES["choice_electric"][1])
    assert len(sim.form_results) == len(_SHAPES["choice_electric"][1])
    # The simulated start is the stored score (no credits on this package).
    shown = sim.measure()[0]
    assert RP._floor(shown) == row["package_sqs"]["package_sqs_score"]


# ── 5. The side panel's door ────────────────────────────────────────────────
def test_the_screen_points_route_serves_the_plan_to_its_owner_only(monkeypatch):
    from fastapi import HTTPException
    from routes import form_routes as FR
    row = _shape("orbin")

    async def _get_row(_sid):
        return copy.deepcopy(row)

    async def _no_rows(_sid):
        return []
    monkeypatch.setattr(FR, "get_processing_session", _get_row)
    from services import audit_service as AU
    monkeypatch.setattr(AU, "get_dismissed_recommendations", _no_rows)
    resp = asyncio.run(FR.get_screen_points("s", {"id": "u", "payment_status": "ok"}))
    body = json.loads(resp.body)
    assert body["success"] is True and body["after_forms"] is True
    assert body["package_sqs"]["review_plan"]["after_forms"] is True
    assert H.plan_problems(body["package_sqs"]) == []
    assert isinstance(body["key_details"], dict) and "grouped_issues" in body
    with pytest.raises(HTTPException) as exc:
        asyncio.run(FR.get_screen_points("s", {"id": "someone-else", "payment_status": "ok"}))
    assert exc.value.status_code == 403


# ── 6. The editor lists the plan's items with the plan's numbers ────────────
def test_the_editor_side_panel_lists_every_plan_item_once_and_they_add_up(tmp_path):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    here = os.path.dirname(os.path.abspath(__file__))
    mod = os.path.normpath(os.path.join(here, "..", "..", "frontend", "src", "utils", "editorPlanList.js"))
    pkg = {
        "package_sqs_score": 79,
        "review_plan": {"after_forms": True, "total": 21, "left": 0, "items": [
            {"id": "kd:Annual revenue", "kind": "detail", "label": "Annual revenue", "points": 2, "exact": True,
             "keys": ["fact:total_revenue"]},
            {"id": "kd:Years in business", "kind": "detail", "label": "Years in business", "points": 2, "exact": True},
            {"id": "card:umb", "kind": "card", "code": "umb", "issue_id": "i9", "label": "Umbrella card",
             "points": 4, "exact": False},
            {"id": "card:zero", "kind": "card", "code": "zero", "issue_id": "i0", "label": "Advisory", "points": 0},
            {"id": "dc:fein", "kind": "dc", "fact": "fein", "label": "fein", "points": 1, "exact": False},
            {"id": "rec:0", "kind": "rec", "row_index": 0, "points": 3, "exact": True},
            {"id": "rec:1", "kind": "rec", "row_index": 1, "points": 0, "mirror_of": "kd:Annual revenue"},
            {"id": "rec:2", "kind": "rec", "row_index": 2, "points": 6, "exact": False},
            {"id": "doc:upload", "kind": "doc", "step": "upload", "label": "Upload loss runs", "points": 3}]},
        "top_recommendations": [
            {"pillar": "structural_completeness", "field": "percent_subcontracted", "action": "Percent subcontracted",
             "plan_id": "rec:0", "answer_gain": 3, "answer_gain_is_exact": True,
             "resolution": {"mode": "field", "facts": ["percent_subcontracted"]}},
            {"pillar": "structural_completeness", "field": "total_revenue", "action": "Annual revenue",
             "plan_id": "rec:1", "answer_gain": 0, "answer_gain_mirror_of": "kd:Annual revenue", "answer_gain_mirror": 2,
             "resolution": {"mode": "field", "facts": ["total_revenue"]}},
            {"pillar": "narrative_quality", "field": "additional_remarks_text", "action": "Narrative",
             "plan_id": "rec:2", "answer_gain": 6, "answer_gain_is_exact": False,
             "resolution": {"mode": "narrative"}}]}
    kd = {"missing_items": [{"label": "Annual revenue", "resolution": {"mode": "field", "facts": ["total_revenue"]}},
                            {"label": "Years in business", "resolution": {"mode": "field", "facts": ["years_in_business"]}}]}
    grouped = {"warnings": {"recommended": [{"code": "umb", "message": "Umbrella card",
                                             "items": [{"code": "umb", "issue_id": "i9", "message": "Umbrella card",
                                                        "resolution": {"mode": "field", "facts": ["umbrella_limit"]}}]}]}}
    js = tmp_path / "t.mjs"
    js.write_text(f"""import {{ editorPlanRows, editorPlanTotal, planAfterForms }} from {json.dumps(mod)};
const pkg = {json.dumps(pkg)};
const list = editorPlanRows(pkg, {json.dumps(kd)}, {json.dumps(grouped)});
console.log(JSON.stringify({{
  ids: list.rows.map((r) => r.id), texts: list.rows.map((r) => r.text),
  total: editorPlanTotal(list), left: list.left, planTotal: list.total,
  cardOpens: !!list.rows.find((r) => r.id === 'card:umb').issue.resolution,
  detailOpens: !!list.rows.find((r) => r.id === 'kd:Annual revenue').item.resolution,
  recOpens: !!list.rows.find((r) => r.id === 'rec:0').scoreItem.resolution,
  before: editorPlanRows({{ ...pkg, review_plan: {{ ...pkg.review_plan, after_forms: undefined }} }}, {{}}, {{}}),
  flag: [planAfterForms(pkg), planAfterForms(null)],
}}));""")
    out = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip())
    assert got["ids"] == ["kd:Annual revenue", "kd:Years in business", "card:umb", "dc:fein", "rec:0", "rec:2",
                          "doc:upload"]
    assert got["texts"] == ["+2 pts", "+2 pts", "up to +4 pts", "up to +1 pts", "+3 pts", "up to +6 pts", "+3 pts"]
    assert got["total"] + got["left"] == got["planTotal"] == 21
    assert got["cardOpens"] and got["detailOpens"] and got["recOpens"]
    assert got["before"] is None and got["flag"] == [True, False]
