"""Hostile review of the reach-100 rule (28 Oct 2026): on any package, answering
every item the pre-form page shows reaches exactly 100, and the points on the
items add up to 100 minus the score. Each test is one defect class the wider
sweep (`reach100_harness.wider_package` / `solve_checked`) found, rebuilt from
scratch - no customer data, no model or network call."""
import copy
import json
import os
import random
import shutil
import subprocess

import pytest

from reach100_harness import _env, plan_problems, read_page, solve_checked, wider_package
from services import review_plan as RP


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("no model or network call")
    import httpx
    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setenv("NARRATIVE_READER", "0")


def _row(lines=("gl",), **extra):
    flags = {{"gl": "has_general_liability", "auto": "has_auto_coverage", "wc": "has_workers_comp",
              "property": "has_property_coverage", "umbrella": "has_umbrella"}[ln]: True for ln in lines}
    f = {
        "applicant_name": _env("Review Test Company LLC"), "fein": _env("12-3456789"),
        "mailing_address": _env("100 Main St, Denver, CO 80202"), "entity_type": _env("LLC"),
        "contact_name": _env("Jordan Example"), "contact_phone": _env("303-555-0199"),
        "contact_email": _env("jordan@example.com"), "producer_name": _env("Example Agency"),
        "operations_description": _env("Accounting and bookkeeping firm."), "naics_code": _env("541211"),
        "total_revenue": _env("1500000"), "total_payroll": _env("500000"), "num_employees": _env("8"),
        "years_in_business": _env("12"), "effective_date": _env("01/15/2027"),
        "expiration_date": _env("01/15/2028"), "prior_carrier": _env("Example Mutual Insurance Company"),
        "gl_each_occurrence": _env("$1,000,000"), "gl_aggregate": _env("$2,000,000"),
    }
    f.update(extra)
    return {"facts": f, "flags": flags, "docs": [], "structured_issues": [],
            "recommendations": [{"form_id": "ACORD_125"}, {"form_id": "ACORD_126"}]}


def _card(code, facts, message="A card."):
    return {"kind": "card", "code": code, "message": message, "id": f"card:{code}",
            "resolution": {"mode": "field", "facts": list(facts)}, "keys": []}


# ── 1. A "verify this figure" card is answered by confirming the figures ──────
def test_a_verify_figure_card_confirms_the_shown_figures_and_stands_down():
    """It typed stand-ins over the payroll AND the revenue, raising the other
    payroll-to-revenue checks the true figures never raise (the page then
    listed 15 points no item added)."""
    from services.issue_registry import figures_verified
    row = _row(("wc",), wc_payroll=_env("1425000"), total_revenue=_env("1500000"))
    sim = RP._Sim(row)
    assert RP._apply(sim, _card("wc_payroll_vs_revenue", ["wc_payroll", "total_revenue"]), {}, 5)
    facts = sim.session["facts"]
    assert facts["wc_payroll"]["value"] == "1425000" and facts["total_revenue"]["value"] == "1500000"
    assert facts["wc_payroll"]["source"] == "producer"
    assert figures_verified("wc_payroll_vs_revenue", facts)


# ── 2. One rule code, several cards: each is weighed ─────────────────────────
def test_every_card_of_a_catch_all_code_is_its_own_item_and_the_points_add_up():
    """`uncovered_soft_stop` drew four cards (lines of business, an expired term,
    the driver schedule, split limits); only the first was weighed, so the rest
    showed nothing and every one printed the first card's number."""
    row = _row(("gl", "auto"), auto_bi_per_person=_env("$500,000"), auto_bi_per_accident=_env("$1,000,000"),
               auto_vin_schedule=_env([{"year": "2019", "make": "Ford", "model": "F-250",
                                        "vin": "1FTBF2B60GEB10001", "cost_new": "45000"}]),
               effective_date=_env("03/15/2024"), expiration_date=_env("03/15/2025"))
    row["flags"]["auto_split_limits"] = True
    row["recommendations"].append({"form_id": "ACORD_127"})
    pkg, _kd, items = read_page(row)
    cards = [i for i in items if i["kind"] == "card" and i["code"] == "uncovered_soft_stop"]
    assert len(cards) >= 2, [i["label"][:60] for i in items]
    assert len({c["id"] for c in cards}) == len(cards)
    assert all(c.get("issue_id") for c in cards)
    assert plan_problems(pkg) == []
    plan_cards = [i for i in pkg["review_plan"]["items"] if i.get("code") == "uncovered_soft_stop"]
    by_code = pkg["screen_card_points"]["uncovered_soft_stop"][0]
    assert by_code == sum(int(i["points"]) for i in plan_cards)       # the code's sum, not the first


# ── 3. An unchanged table save that derives facts counts ─────────────────────
def test_saving_a_complete_wc_table_unchanged_derives_the_state_breakdown():
    """The multi-state card's fix is the WC class table; a complete table's save
    derives `wc_payroll_by_state`. An unchanged table was 'nothing to do' in the
    plan, so the card showed 0 and the solver stalled at 85."""
    row = _row(("gl", "wc"), wc_payroll=_env("500000"),
               wc_class_codes=_env([{"code": "8810", "description": "Clerical", "state": "CO",
                                     "payroll": "500000"}]))
    row["flags"]["wc_multi_state"] = True
    row["recommendations"].append({"form_id": "ACORD_130"})
    sim = RP._Sim(row)
    assert sim.table("wc_class_codes", {"mode": "schedule", "schedule_key": "wc_class_codes"})
    assert RP._fv(sim.session["facts"], "wc_payroll_by_state")
    assert not sim.table("wc_class_codes", {"mode": "schedule", "schedule_key": "wc_class_codes"})
    score, problems = solve_checked(row)
    assert score == 100 and problems == [], problems


# ── 4. A card about a wrong stated value that also lists an empty box ─────────
def test_a_backwards_term_card_with_an_empty_umbrella_box_corrects_the_term():
    msg = ("Effective date is on or after expiration date in the dates read from your "
           "documents. Fix: Correct the proposed effective or expiration date.")
    row = _row(("gl",), effective_date=_env("01/15/2026"), expiration_date=_env("01/15/2026"))
    sim = RP._Sim(row)
    from services.stops_now import stops_now
    assert msg in stops_now(row, pre_form=True)["soft"]
    item = _card("uncovered_soft_stop", ["effective_date", "expiration_date", "umbrella_expiration_date"], msg)
    assert RP._apply(sim, item, {}, 5)
    assert msg not in stops_now(sim.session, pre_form=True, facts=sim.session["facts"],
                                flags=sim.session["flags"])["soft"]
    assert sim.session["facts"]["effective_date"]["source"] == "producer"


# ── 5. The items behind an empty vehicle schedule are listed up front ─────────
def test_garaging_radius_and_use_are_listed_up_front_beside_the_vehicle_schedule():
    """A vehicle added to an empty schedule used to ask for garaging, radius and
    use as items not yet on the page (the auto bucket listed its gaps only up to
    its cap). Rule G2 (owner, 30 Oct 2026): every item is listed up front - the
    capped bucket shares its points over every gap - and the page adds up.
    (Updated 30 Oct 2026: this test pinned the old follow-up behaviour.)"""
    row = _row(("gl", "auto"), auto_liability_limit=_env("$1,000,000"))
    row["recommendations"].append({"form_id": "ACORD_127"})
    pkg, _kd, items = read_page(row)
    assert plan_problems(pkg) == []
    keys = {k for i in items for k in (i.get("keys") or [])}
    for fact in ("auto_garaging_addresses", "auto_radius_of_operation", "auto_vehicle_use"):
        assert any(k.endswith(fact) for k in keys), (fact, sorted(keys))
    leads = [i for i in pkg["review_plan"]["items"] if i.get("leads_to")]
    assert not any("Garaging" in " ".join(i["leads_to"]) for i in leads)


# ── 6. The sample answer that raises nothing new ─────────────────────────────
def test_the_employee_count_sample_does_not_raise_a_workers_comp_gap_on_a_package_without_it():
    """"25 employees" on a package carrying no workers comp raised "Employees are
    listed but no workers comp coverage is carried" (-8) - points no item on the
    page added. Since 30 Oct 2026 (rule G2) the sample itself agrees with the
    package's coverage (`probe_value` stands in 5 on a package without WC), so
    the first answer raises nothing. (Updated: this test pinned the retry with
    another sample after the first raised the gap.)"""
    row = _row(("gl",))
    row["facts"].pop("num_employees")
    sim = RP._Sim(row)
    sim.choose_samples = True
    seen = RP._raised(sim)
    item = {"kind": "detail", "id": "kd:n", "label": "Number of employees", "keys": ["fact:num_employees"],
            "resolution": {"mode": "field", "facts": ["num_employees"]}}
    sim.step_samples = []
    assert RP._apply(sim, item, {}, 5)
    assert not (RP._raised(sim) - seen)
    pkg, _kd, _items = read_page(row)
    assert plan_problems(pkg) == []
    # Off the plan (the real solver, the answer preview) the sample is unchanged.
    plain = RP._Sim(row)
    assert RP._best_sample(plain, "num_employees") == RP.probe_value("num_employees", row["facts"], row)
    assert plain.step_samples == []


# ── 7. Minimum Viable COPE always offers the premises box it checks ──────────
def test_the_minimum_viable_cope_card_shows_the_premises_box_when_no_premises_is_stated():
    from services.issue_registry import resolution_for
    from services.premises_cope import route_cope_resolution
    for code in ("minimum_viable_cope_missing", "legacy_minimum_viable_cope"):
        base = resolution_for(code)
        assert route_cope_resolution(code, base, {})["facts"][0] == "locations"
        assert route_cope_resolution(code, base, {"locations": ["1 Main St"]}) is base


def test_a_premises_address_answered_none_is_still_answerable_on_the_hard_stop():
    """'Premises address' answered 'None' took its row off the page; the COPE
    hard stop (60) then named a box nothing offered - a dead end."""
    row = _row(("gl", "property"), occupancy_type=_env("Office"), construction_type=_env("Masonry"),
               property_building_value=_env("500000"), coinsurance_percentage=_env("80"))
    row["recommendations"].append({"form_id": "ACORD_140"})
    sim = RP._Sim(row)
    sim.answer("locations", "None")
    from services.stops_now import stops_now
    hard = stops_now(sim.session, pre_form=True, facts=sim.session["facts"], flags=sim.session["flags"])["hard"]
    assert any("Minimum Viable COPE" in m and "locations" in m for m in hard)
    _pkg, _kd, items = read_page(sim.session)
    cope = [i for i in items if i["kind"] == "card" and "Minimum Viable COPE" in i["label"]]
    assert cope and "locations" in (cope[0]["resolution"].get("facts") or [])
    score, problems = solve_checked(sim.session)
    assert score == 100, problems


# ── 8. An empty table save over an empty table saves nothing ─────────────────
def test_an_empty_table_save_is_refused_and_emptying_a_full_one_still_saves(monkeypatch):
    import asyncio
    from repositories import session_repository as sr
    from services.arq_service import save_session_schedule
    store = {"facts": {}, "generated_forms": {}}
    writes = []

    async def _get(_sid):
        return copy.deepcopy(store)

    async def _upd(_sid, payload, **_kw):
        writes.append(payload)
    monkeypatch.setattr(sr, "get_processing_session", _get)
    monkeypatch.setattr(sr, "upd_processing_session", _upd)
    ok, out = asyncio.run(save_session_schedule("s", "auto_drivers", []))
    assert ok is False and writes == [] and out.get("nothing_to_save")
    store["facts"] = {"auto_drivers": _env([{"name": "Pat Driver", "dob": "01/01/1980",
                                             "license_number": "D1234567", "license_state": "CO"}])}
    ok, _out = asyncio.run(save_session_schedule("s", "auto_drivers", []))
    assert ok is True and len(writes) == 1                              # a retraction is a save


# ── 9. The page finds each card's own number ─────────────────────────────────
@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_the_page_reads_each_card_by_its_issue_id(tmp_path):
    here = os.path.dirname(os.path.abspath(__file__))
    mod = os.path.normpath(os.path.join(here, "..", "..", "frontend", "src", "utils", "screenPoints.js"))
    plan = {"review_plan": {"items": [
        {"id": "card:x", "kind": "card", "code": "x", "issue_id": "i1", "points": 3},
        {"id": "card:x#i2", "kind": "card", "code": "x", "issue_id": "i2", "points": 5}]}}
    js = tmp_path / "t.mjs"
    js.write_text(f"""import {{ screenPoints, cardPoints }} from {json.dumps(mod)};
const sp = screenPoints({json.dumps(plan)}, {{}}, {{}});
console.log(JSON.stringify([cardPoints(sp.cards, {{code: 'x', issue_id: 'i2'}}).points,
  cardPoints(sp.cards, {{code: 'x', issue_id: 'i1'}}).points, cardPoints(sp.cards, {{code: 'x'}}).points]));""")
    out = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout.strip()) == [5, 3, 3]


# ── 10. The wider generator, a fixed handful ─────────────────────────────────
@pytest.mark.parametrize("seed", (203, 205, 206, 208, 209, 211))
def test_wider_packages_reach_exactly_100_and_the_numbers_add_up(seed):
    row = wider_package(random.Random(seed))
    score, problems = solve_checked(row)
    assert score == 100 and problems == [], (row["_tags"], score, problems)


# ── 11. A card answered by an explanation is recorded as explained ───────────
def test_a_narrative_card_answered_in_the_plan_is_recorded_as_explained_like_the_real_door():
    """`resolve_issue` mode=narrative keeps the card's code in
    `_explained_issue_codes` (its rule then stops counting it); the plan's copy
    wrote the remarks only, so the card stood and its points showed nowhere."""
    from services.issue_registry import explained_issue_codes
    sim = RP._Sim(_row(("gl", "wc")))
    item = {"kind": "card", "code": "wc_gl_class_code_mismatch", "message": "Class codes disagree.",
            "id": "card:wc_gl_class_code_mismatch", "keys": [],
            "resolution": {"mode": "narrative", "gaps": []}}
    assert RP._apply(sim, item, {}, 5)
    assert "wc_gl_class_code_mismatch" in explained_issue_codes(sim.session["facts"])
    RP._apply(sim, item, {}, 5)                         # a second save: the code is kept once
    assert explained_issue_codes(sim.session["facts"]) == {"wc_gl_class_code_mismatch"}


# ── 12. A proposed-term save the route would refuse is never credited ────────
def test_the_proposed_effective_date_detail_opens_both_term_dates_and_saves_a_whole_term():
    """A document's ENDED expiration beside a missing effective date: the key
    detail's window held only the effective date, the real save of it was
    refused ("the term would run backwards"), yet the plan credited it."""
    from services import sqs_service as S
    from utils.validators import term_save_refusal
    row = _row(("gl",), expiration_date=_env("05/15/2026"))
    row["facts"].pop("effective_date")
    kd = S.key_details(row["facts"], row["flags"])
    item = next(i for i in kd["missing_items"] if "effective" in str(i.get("label", "")).lower())
    assert item["resolution"]["facts"] == ["effective_date", "expiration_date"]
    sim = RP._Sim(row)
    plan_item = {"kind": "detail", "id": "kd:x", "label": item["label"], "resolution": item["resolution"]}
    assert RP._apply(sim, plan_item, {}, 5)
    f = sim.session["facts"]
    assert f["effective_date"]["source"] == f["expiration_date"]["source"] == "producer"
    assert term_save_refusal(row["facts"], {"effective_date": f["effective_date"]["value"],
                                            "expiration_date": f["expiration_date"]["value"]}) == ""
    # A window with no partner box saves nothing rather than a refused term.
    sim2 = RP._Sim(row)
    lone = {"kind": "detail", "id": "kd:y", "label": "x",
            "resolution": {"mode": "field", "facts": ["effective_date"]}}
    assert RP._apply(sim2, lone, {}, 5) is False
    assert "effective_date" not in sim2.session["facts"]


# ── 13. The narrative window lists the topics as the page stands when opened ─
def test_the_narrative_step_writes_the_topics_the_page_needs_now_not_only_the_page_start_list():
    """The plan wrote the topics the page listed at its start; answers above
    the narrative row had added two (growth, target markets), so the narrative
    ended at 89 and the plan listed points no item added."""
    def narrative():
        sim.measure()
        p = sim.last_pkg["pillars"]["narrative_quality"]
        return p.get("score") if isinstance(p, dict) else p

    sim = RP._Sim(_row(("gl",)))
    assert narrative() < 100
    stale = {"kind": "rec", "id": "rec:n", "label": "Narrative", "prose": True, "keys": [],
             "resolution": {"mode": "narrative", "gaps": []}}          # the page-start list: nothing left
    assert RP._apply(sim, stale, {}, 5)
    assert narrative() == 100
