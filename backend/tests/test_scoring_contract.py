"""THE SCORING CONTRACT (owner, 29 Oct 2026 - SCORING_RULES.md R1-R4, P1-P6).

Proved on random packages, not on the packages we have seen:
  * every reading of the page: P1 (a score item below 100 shows a number or
    "under 1 pt"), P2 (the items add up to exactly 100 - score, nothing on no
    item), P4 (no negative, a mirror adds nothing), P5 (a non-score item carries
    no number) - and the plan's own guard (`review_plan.enforce_contract`) had
    nothing to repair;
  * answering everything the page lists - in page order, reverse, shuffled,
    with the plan's sample answers and with a person's own answers - ends at
    exactly 100 (R2), never sticks below it (R3), never passes it (R4), and the
    page adds up after every step (P2);
  * the same after forms (the editor's side panel) and on the download screen
    (`utils/downloadPlanPoints.js`, node).

The packages are `reach100_harness.contract_package` (built on `wider_package` and
`synthetic_package`: random line mixes, ACORD-read facts, two documents
disagreeing on a random fact, random loss histories, several holds at once).
No model or network call. The slow sweep (hundreds of packages) is
`SCORING_CONTRACT_SWEEP=N`.
"""
import copy
import json
import os
import random
import shutil
import subprocess
import textwrap

import pytest

import reach100_harness as H
from services import review_plan as RP

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONT = os.path.normpath(os.path.join(BACKEND, "..", "frontend", "src", "utils"))


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("the scoring contract check must make no model or network call")
    import httpx
    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setenv("NARRATIVE_READER", "0")
    monkeypatch.setenv("EVIDENCE_JUDGE", "0")
    monkeypatch.setenv("CARRIER_NARRATIVE", "0")


# ── 1. The guard itself ──────────────────────────────────────────────────────
def _it(i, pts=0, **kw):
    return {"id": i, "kind": kw.pop("kind", "card"), "points": pts, "score_item": kw.pop("score_item", True),
            "gain": kw.pop("gain", 0.0), "_own": kw.pop("own", 0.0), **kw}


def test_guard_leaves_a_plan_that_keeps_the_contract_alone(caplog):
    items = [_it("a", 3, exact=True), _it("b", 0, under=True), _it("c", 2, mirror_of=None)]
    left, rep = RP.enforce_contract(items, 95, 0)
    assert (left, rep) == (0, [])
    assert [i["points"] for i in items] == [3, 0, 2] and items[1]["under"] is True
    assert "SCORING_CONTRACT_REPAIRED" not in caplog.text


def test_guard_repairs_every_breach_and_logs_no_values(caplog):
    items = [_it("kd:Annual revenue", 7, gain=7.0), _it("neg", -2),
             _it("m", 2, mirror_of="kd:Annual revenue"), _it("zero", 0, held_by="Proposed term", gain=0.4),
             _it("off", 1, score_item=False)]
    with caplog.at_level("WARNING"):
        left, rep = RP.enforce_contract(items, 90, 0)
    live = [i for i in items if not i.get("mirror_of")]
    assert sum(i["points"] for i in live) == 10 and left == 0           # P2
    assert all(i["points"] >= 0 for i in items)                          # P4
    assert items[2]["points"] == 0                                       # mirror adds nothing
    assert items[3]["under"] and items[3]["held_by"] is None             # P1, never "counts once"
    assert "counts when Proposed term is fixed" in items[3]["with_others"]
    assert items[4]["score_item"] is True                                # a number = a score item
    assert {r.split(":")[0] for r in rep} >= {"P4 negative", "P4 mirror counted twice", "P5 number on a non-score item"}
    assert "SCORING_CONTRACT_REPAIRED" in caplog.text


def test_guard_gives_points_no_item_carried_to_a_score_item():
    items = [_it("a", 2, gain=2.0), _it("b", 0, under=True, gain=0.6)]
    left, rep = RP.enforce_contract(items, 95, 3)
    assert left == 0 and sum(i["points"] for i in items) == 5
    assert items[1]["points"] >= 1 and not items[1]["under"]
    assert rep and rep[0].startswith("P2 short")


def test_guard_at_100_lists_no_number():
    items = [_it("a", 1, gain=1.0), _it("b", 0, under=True)]
    left, rep = RP.enforce_contract(items, 100, 0)
    assert all(i["points"] == 0 and not i["under"] and i["score_item"] is False for i in items)
    assert left == 0 and rep


def test_holders_outnumbering_a_release_show_under_1_pt_never_a_borrowed_point():
    """11 warnings sharing a 4-point release: 4 show +1, the other 7 "under 1 pt"
    (P1 + P3 - no item gives up its own measured gain)."""
    items = [_it(f"w{k}", 0, _cleared=["soft"], _did=True) for k in range(10)]
    items.append(_it("last", 4, gain=4.0, _cleared=["soft"], _released=["soft"], _did=True))
    RP._share_group_releases(items, 4, {"soft": 11})
    RP._no_listed_zero(items, None)
    left, rep = RP.enforce_contract(items, 96, 0)
    assert rep == [] and left == 0
    assert sum(i["points"] for i in items) == 4
    assert sum(1 for i in items if i["points"] == 0 and i["under"]) == 7
    assert all("counts when all 11 warnings are fixed" == i["with_others"] for i in items)


# ── 2. Random packages: every reading, every order ───────────────────────────
_BUILD_SEEDS = tuple(range(5001, 5041))       # 40 fixed seeds in the build
_MODES = ("page", "reverse", "shuffle", "honest")


@pytest.mark.parametrize("seed", _BUILD_SEEDS)
def test_random_package_keeps_the_contract(seed):
    row = H.contract_package(random.Random(seed))
    pkg, _kd, _items = H.read_page(row)
    start = H.contract_problems(pkg)
    assert start == [], (row["_tags"], pkg.get("package_sqs_score"), start)
    mode = _MODES[seed % len(_MODES)]
    score, problems, _final = H.solve_contract(
        row, order="page" if mode == "honest" else mode, rnd=random.Random(seed),
        honest=(mode == "honest"), every_step=(mode == "page"))
    assert score == 100 and problems == [], (row["_tags"], mode, score, problems)


def test_a_package_already_at_100_lists_no_number():
    row = H.contract_package(random.Random(5003))
    score, problems, final = H.solve_contract(row, every_step=False)
    assert score == 100 and problems == []
    pkg, _kd, _items = H.read_page(final)
    assert pkg["package_sqs_score"] == 100 and H.contract_problems(pkg) == []
    plan = pkg.get("review_plan") or {}
    assert all(not i.get("points") and not i.get("under") for i in plan.get("items") or [])


def test_a_package_held_only_by_a_hard_stop():
    """Everything answered, then the proposed term taken away: the one hard stop
    carries every point to 100 and its answer reaches it."""
    row = H.contract_package(random.Random(5005))
    _s, _p, final = H.solve_contract(row, every_step=False)
    for k in ("effective_date", "expiration_date"):
        final["facts"].pop(k, None)
        for d in final.get("docs") or []:
            (d.get("facts") or {}).pop(k, None)
    pkg, _kd, _items = H.read_page(final)
    assert pkg["package_sqs_score"] < 100 and H.contract_problems(pkg) == []
    score, problems, _f = H.solve_contract(final, every_step=True)
    assert score == 100 and problems == [], problems


def test_a_class_code_mismatch_row_offers_the_side_it_compares_with():
    """Root cause (29 Oct 2026 sweep): a WC / GL class-code mismatch row opened
    the codes table only; with codes and description both on file a person
    could not clear it there, the plan listed it "No effect on the score" and
    its points sat on no item. The row now also offers the operations
    description and NAICS (`also_facts`)."""
    row = H.contract_package(random.Random(5002))
    _s, _p, final = H.solve_contract(row, every_step=False)
    final["flags"]["has_workers_comp"] = True
    final["facts"]["operations_description"] = H._env("Full service restaurant serving lunch and dinner.")
    final["facts"]["wc_class_codes"] = H._env([{"code": "5190", "description": "Electrical", "state": "CO",
                                                "payroll": "300000"}])
    final["facts"]["wc_payroll"] = H._env("300000")
    pkg, _kd, items = H.read_page(final)
    rows = [i for i in items if i["kind"] == "rec" and i.get("field") == "wc_class_codes"]
    if not rows:
        pytest.skip("the codes on this seed do not read as a mismatch")
    assert set(rows[0]["resolution"].get("facts") or []) >= {"operations_description", "naics_code"}
    assert H.contract_problems(pkg) == []
    score, problems, _f = H.solve_contract(final, every_step=False)
    assert score == 100 and problems == [], problems


# ── 3. After forms: the editor's side panel ──────────────────────────────────
def _generated(fids):
    return {f: {"form_id": f, "form_name": f, "sqs": {"form_id": f, "sqs_score": 80}} for f in fids}


def _rescore(row: dict) -> None:
    from services import sqs_service as S
    from services.stops_now import stops_now
    st = stops_now(row, None, pre_form=False)
    row["package_sqs"] = S.calculate_package_sqs(
        facts=row["facts"], flags=row.get("flags") or {},
        form_results=[f["sqs"] for f in (row.get("generated_forms") or {}).values()],
        cross_issues=st["cross_issues"], hard_stops=st["hard"], soft_stops=st["soft"],
        session_data=row, calculation_stage="arq_remediated")


def _read_after_forms(row: dict):
    from routes.form_routes import screen_points_after_forms
    _rescore(row)
    out = screen_points_after_forms(row, "s", "u", None)
    pkg, kd, grouped = out["package_sqs"], out["key_details"], out["grouped_issues"]
    return pkg, kd, RP.page_items(row, pkg, kd, grouped)


@pytest.mark.parametrize("seed", (5101, 5102, 5103, 5104, 5105, 5106))
def test_after_forms_the_side_panel_keeps_the_contract(seed):
    import logging
    logging.getLogger("services.audit_service").setLevel(logging.CRITICAL)
    row = H.contract_package(random.Random(seed))
    fids = [r["form_id"] for r in row["recommendations"]]
    row["selected_form_ids"], row["generated_forms"], row["user_id"] = list(fids), _generated(fids), "u"
    pkg, _kd, _items = _read_after_forms(copy.deepcopy(row))
    assert H.contract_problems(pkg) == [], (row["_tags"], H.contract_problems(pkg))
    score, problems, _f = H.solve_contract(row, order="reverse" if seed % 2 else "page",
                                           every_step=False, reader=_read_after_forms)
    assert score == 100 and problems == [], (row["_tags"], score, problems)


# ── 4. The download screen prints the plan's numbers (node) ─────────────────
def test_download_screen_numbers_add_up_and_print_under_1_pt(tmp_path):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    sqs, rows = None, []
    for seed in range(5201, 5231):
        row = H.contract_package(random.Random(seed))
        pkg, _kd, _items = H.read_page(row)
        plan = pkg.get("review_plan") or {}
        if any(i.get("under") for i in plan.get("items") or []):
            sqs = pkg
            break
    if sqs is None:
        pytest.skip("no package with an under-1-pt item in these seeds")
    sqs = json.loads(json.dumps(sqs, default=str))
    sqs["review_plan"]["after_forms"] = True
    for it in sqs["review_plan"]["items"]:
        if it.get("kind") == "card":
            rows.append({"rec_id": it["id"], "issue_id": it.get("issue_id"), "code": it.get("code"),
                         "review_issue": True})
        elif it.get("kind") == "rec":
            rows.append({"rec_id": it["id"], "field": it.get("field")})
    data = tmp_path / "in.json"
    data.write_text(json.dumps({"sqs": sqs, "rows": rows}))
    js = tmp_path / "t.mjs"
    js.write_text(textwrap.dedent(f"""
        import fs from "fs";
        import {{ downloadPlanPoints }} from {json.dumps("file://" + os.path.join(FRONT, "downloadPlanPoints.js"))};
        import {{ screenPointsText }} from {json.dumps("file://" + os.path.join(FRONT, "screenPoints.js"))};
        const {{ sqs, rows }} = JSON.parse(fs.readFileSync({json.dumps(str(data))}, "utf8"));
        const m = downloadPlanPoints(sqs, rows);
        const texts = [...m.values()];
        const sum = texts.reduce((n, t) => n + (Number((t.match(/\\+(\\d+) pts?/) || [])[1]) || 0), 0);
        const under = screenPointsText({{ points: 0, under: true, withOthers: "counts when all 3 warnings are fixed" }});
        console.log(JSON.stringify({{ sum, texts, under, zero: texts.filter((t) => t === "+0 pts").length }}));
    """))
    out = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    res = json.loads(out.stdout.strip().splitlines()[-1])
    total = 100 - int(sqs["package_sqs_score"])
    assert res["sum"] <= total and res["zero"] == 0, res
    assert res["under"] == "under 1 pt (counts when all 3 warnings are fixed)"


# ── 5. The slow sweep (hundreds of packages) ─────────────────────────────────
_SWEEP = int(os.environ.get("SCORING_CONTRACT_SWEEP") or 0)


@pytest.mark.skipif(not _SWEEP, reason="set SCORING_CONTRACT_SWEEP=N to run the slow sweep")
def test_slow_sweep_every_order_every_answer():
    bad = []
    for seed in range(9000, 9000 + _SWEEP):
        row = H.contract_package(random.Random(seed))
        pkg, _kd, _items = H.read_page(row)
        probs = H.contract_problems(pkg)
        for mode in ("page", "reverse", "shuffle", "shuffle", "shuffle", "honest"):
            _s, p, _f = H.solve_contract(row, order="page" if mode == "honest" else mode,
                                         rnd=random.Random(seed * 7 + len(bad)), honest=(mode == "honest"),
                                         every_step=(mode == "page"))
            probs += [f"{mode}: {x}" for x in p]
        if probs:
            bad.append((seed, row["_tags"], probs[:4]))
    assert not bad, bad[:10]
