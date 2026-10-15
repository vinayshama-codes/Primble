"""The points the screen lists add up to what answering them makes - never past 100
(owner, 15 Oct 2026, live run 5eb5b23c).

At 94 the Recommendations section listed three rows: +3 / +2 / +2. "If I solve these
all I will gain 7 points and that will take my score to 101, but that's wrong." It
was: each number was its answer measured ALONE, and the score is a weighted sum
rounded DOWN - every lone probe collected the same leftover fraction of a point, so
the three lone gains (2.4, 1.5, 1.5 against a 94.6) read 3 + 2 + 2 while answering all
three makes exactly 100. The owner's rule: "score should be distributed in such a
manner that it should not go past 100 ... correct for all the packages".

Every number is now a SHARE of one measured total (`sqs_service._share_out_gains`):
the answers go in one after another and each takes what the rounded score moved, so
the shares add up exactly to answering them all. A card asking the same thing shows
the same share; a number that is not a share (no probe, a card's typed bound) takes
at most what is left below 100; the page caps whatever it works out itself
(`recommendations.withinHundred`).
"""
import json
import math
import pathlib
import random
import shutil
import subprocess

import pytest

from services import sqs_service as S

ROOT = pathlib.Path(__file__).resolve().parents[2]
UTIL = ROOT / "frontend" / "src" / "utils" / "recommendations.js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

# Real fields, so the probe answers are the ones the live scorer uses.
SUB, RAD, USE = "percent_subcontracted", "auto_radius_of_operation", "auto_vehicle_use"
EXTRA = ["distance_to_hydrant", "fire_department_type", "year_built", "roof_year",
         "fire_protection_class", "sprinkler_system", "construction_type", "occupancy_type"]


def _row(field, pillar="exposure_consistency", score=82):
    return {"pillar": pillar, "score": score, "field": field, "action": field, "missing": []}


def _card(rec_id, field, declared=None, component="exposure_consistency"):
    return {"rec_id": rec_id, "field": field, "component": component,
            "score_impact": declared, "priority": 1}


def _floored(raw, effect):
    """A rescore whose package score is `raw` plus `effect(answered fields)`, rounded
    DOWN and held at 100 - the scorer's own arithmetic."""
    def rescore(facts):
        return int(math.floor(round(min(100.0, raw + effect(set(facts))), 9)))
    return rescore


def _unify(rows, rescore, raw, cards=(), cap=None):
    forms = [{"form_id": "ACORD_125", "recommendations": [dict(c) for c in cards]}]
    S._unify_card_points(forms, rows, {}, int(math.floor(raw)), cap, lambda _c: None, rescore)
    return forms[0]["recommendations"]


def _shown(rows, cards=()):
    """Every number the screen shows, once per field."""
    seen = {}
    for r in rows:
        if r.get("field") and isinstance(r.get("answer_gain"), int):
            seen.setdefault(r["field"], r["answer_gain"])
    for c in cards:
        if c.get("field") and isinstance(c.get("score_impact"), int):
            seen.setdefault(c["field"], c["score_impact"])
    return seen


# ── The live case ────────────────────────────────────────────────────────────
def test_the_live_94_adds_up_to_exactly_100():
    deltas = {SUB: 2.4, RAD: 1.5, USE: 1.5}
    rescore = _floored(94.6, lambda f: sum(d for k, d in deltas.items() if k in f))
    rows = [_row(SUB), _row(RAD), _row(USE)]
    _unify(rows, rescore, 94.6)
    assert [r["answer_gain"] for r in rows] == [3, 1, 2]
    assert [r["answer_gain_alone"] for r in rows] == [3, 2, 2]
    assert all(r["answer_gain_share"] is True for r in rows)
    assert all(r["answer_gain_is_exact"] is True for r in rows)     # none promises more than alone
    assert 94 + sum(r["answer_gain"] for r in rows) == 100


def test_the_biggest_answer_keeps_its_full_value_wherever_it_is_listed():
    deltas = {SUB: 2.4, RAD: 1.5, USE: 1.5}
    rescore = _floored(94.6, lambda f: sum(d for k, d in deltas.items() if k in f))
    rows = [_row(RAD), _row(USE), _row(SUB)]
    _unify(rows, rescore, 94.6)
    by = {r["field"]: r["answer_gain"] for r in rows}
    assert by[SUB] == 3 and sum(by.values()) == 6


# ── The shapes lone gains get wrong ──────────────────────────────────────────
def test_two_answers_clearing_one_deduction_share_it():
    rescore = _floored(90.0, lambda f: 5 if (SUB in f or RAD in f) else 0)
    rows = [_row(SUB), _row(RAD)]
    _unify(rows, rescore, 90.0)
    assert [r["answer_gain"] for r in rows] == [5, 0]
    # the second is still worth 5 on its own - the page keeps it listed, unnumbered
    assert rows[1]["answer_gain_alone"] == 5


def test_rows_held_by_a_gate_take_what_the_gate_unlocks():
    gate, h1, h2 = "occupancy_type", "distance_to_hydrant", "fire_department_type"

    def effect(f):
        if gate not in f:
            return 0
        return 8 + (3 if h1 in f else 0) + (3 if h2 in f else 0)
    rows = [_row(h1, "property_integrity", 0), _row(h2, "property_integrity", 0),
            _row(gate, "property_integrity", 0)]
    _unify(rows, _floored(70.0, effect), 70.0)
    by = {r["field"]: r for r in rows}
    assert by[gate]["answer_gain"] == 8 and by[gate]["answer_gain_is_exact"] is True
    for h in (h1, h2):
        assert by[h]["answer_gain"] == 3 and by[h]["answer_gain_alone"] == 0
        assert by[h]["answer_gain_is_exact"] is False                # nothing on its own: "up to"
    assert sum(r["answer_gain"] for r in rows) == 14 == effect({gate, h1, h2})


def test_fractions_too_small_alone_still_reach_the_total():
    # Z19's two COPE rows: 79.00 -> 79.88 each alone (+0), 80.76 together (+1)
    a, b = "distance_to_hydrant", "fire_department_type"
    rescore = _floored(79.0, lambda f: 0.88 * len({a, b} & f))
    rows = [_row(a, "property_integrity", 90), _row(b, "property_integrity", 90)]
    _unify(rows, rescore, 79.0)
    assert [r["answer_gain"] for r in rows] == [0, 1]
    assert rows[1]["answer_gain_is_exact"] is False


def test_an_answer_that_costs_points_after_the_others_takes_no_share():
    # USE adds 1 alone, but takes 4 off once SUB is in: answering all three
    # makes 80 + 3 + 2 - 4 = 81. The list says +1, never +5.
    def effect(f):
        e = (3 if SUB in f else 0) + (2 if RAD in f else 0)
        return e - 4 if (USE in f and SUB in f) else e + (1 if USE in f else 0)
    rows = [_row(SUB), _row(RAD), _row(USE)]
    rescore = _floored(80.0, effect)
    _unify(rows, rescore, 80.0)
    by = {r["field"]: r["answer_gain"] for r in rows}
    assert by[USE] == 0
    assert sum(by.values()) == rescore({SUB, RAD, USE}) - 80 == 1
    assert by[SUB] == 1 and by[RAD] == 0      # its cost came off the smaller shares first


def test_a_ceiling_reached_part_way_down_is_never_promised_past():
    rescore = _floored(80.0, lambda f: 3 * len({SUB, RAD, USE} & f))
    rows = [_row(SUB), _row(RAD), _row(USE)]
    _unify(rows, rescore, 80.0, cap=85)
    assert [r["answer_gain"] for r in rows] == [3, 3, 3]
    assert [r["answer_gain_is_exact"] for r in rows] == [True, False, False]


# ── Cards: one number per field, one total for the whole screen ──────────────
def test_a_card_and_a_row_asking_one_thing_show_one_share():
    deltas = {SUB: 2.4, RAD: 1.5, USE: 1.5}
    rescore = _floored(94.6, lambda f: sum(d for k, d in deltas.items() if k in f))
    rows = [_row(SUB), _row(RAD), _row(USE)]
    cards = _unify(rows, rescore, 94.6, cards=[_card("rec_rad", RAD, 5), _card("rec_use", USE, 5)])
    by_card = {c["field"]: c["score_impact"] for c in cards}
    by_row = {r["field"]: r["answer_gain"] for r in rows}
    assert by_card == {RAD: by_row[RAD], USE: by_row[USE]}
    assert all(c["impact_scope"] == "package" for c in cards)


def test_a_cards_own_field_joins_the_total():
    deltas = {SUB: 2.4, RAD: 1.5, "fire_protection_class": 1.5}
    rescore = _floored(94.6, lambda f: sum(d for k, d in deltas.items() if k in f))
    rows = [_row(SUB), _row(RAD)]
    cards = _unify(rows, rescore, 94.6, cards=[_card("rec_pc", "fire_protection_class", 4, "property_integrity")])
    assert sum(_shown(rows, cards).values()) == 6 == 100 - 94


def test_a_typed_bound_takes_only_what_is_left_below_100():
    deltas = {SUB: 2.4, RAD: 1.5, USE: 1.5}

    def rescore(f):
        if "loss_history_prior_claims" in f:
            raise RuntimeError("no probe for this one")
        return _floored(94.6, lambda g: sum(d for k, d in deltas.items() if k in g))(f)
    rows = [_row(SUB), _row(RAD), _row(USE)]
    cards = _unify(rows, rescore, 94.6, cards=[_card("rec_loss", "loss_history_prior_claims", 12, "loss_history_alignment")])
    loss = next(c for c in cards if c["rec_id"] == "rec_loss")
    assert loss["score_impact"] == 0                     # the shares took all six points
    assert sum(_shown(rows, cards).values()) <= 6


def test_unscored_cards_stay_at_zero():
    rescore = _floored(90.0, lambda f: 4 if SUB in f else 0)
    rows = [_row(SUB)]
    card = dict(_card("rec_landlord", "landlord_name", 0), unscored=True)
    cards = _unify(rows, rescore, 90.0, cards=[card])
    assert cards[0]["score_impact"] == 0 and cards[0]["impact_is_exact"] is True


# ── For every package: never past 100, and exactly the total when all is measured ──
@pytest.mark.parametrize("seed", range(60))
def test_no_package_lists_more_than_answering_everything_makes(seed):
    rng = random.Random(seed)
    fields = [SUB, RAD, USE] + EXTRA
    for _ in range(40):
        k = rng.randint(1, 8)
        chosen = rng.sample(fields, k)
        raw = rng.uniform(30.0, 99.9)
        deltas = {f: rng.choice([0, 0.3, 0.6, 0.88, 1.5, 2.4, 3.7, 5.0, 8.0]) for f in chosen}
        pairs = [tuple(rng.sample(chosen, 2)) for _ in range(rng.randint(0, 2))] if k > 1 else []
        gate = rng.choice(chosen) if rng.random() < 0.3 else None

        def effect(f, deltas=deltas, pairs=pairs, gate=gate):
            if gate and gate not in f:
                return 0.0
            e = sum(d for x, d in deltas.items() if x in f)
            for x, y in pairs:                       # two answers clearing one deduction
                if x in f and y in f:
                    e -= min(deltas[x], deltas[y])
            return e
        rescore = _floored(raw, effect)
        n_rows = rng.randint(0, k)
        rows = [_row(f, score=rng.choice([0, 60, 90])) for f in chosen[:n_rows]]
        cards = [_card(f"rec_{f}", f, rng.choice([None, 3, 7, 15])) for f in chosen[n_rows:]]
        cap = rng.choice([None, None, 85, 60])
        out_cards = _unify(rows, rescore, raw, cards=cards, cap=cap)
        shown = _shown(rows, out_cards)
        now = int(math.floor(round(raw, 9)))
        assert sum(shown.values()) <= 100 - now, (seed, raw, deltas, shown)
        assert all(v >= 0 for v in shown.values())
        # every row that carries a share promises nothing it does not give alone
        for r in rows:
            if r.get("answer_gain_share") and r.get("answer_gain_is_exact") and r["answer_gain"] > 0:
                assert r["answer_gain"] <= r["answer_gain_alone"]
        # the shares add up to exactly what the answers that went in make
        shared = {r["field"] for r in rows if r.get("answer_gain_share")}
        if shared and len(shared) == len(rows) and not cards:
            gains = {f: (rescore({f}) - now, True) for f in shared}
            share, _base, room, applied = S._share_out_gains(
                [r["field"] for r in rows], [], gains, {f: "x" for f in shared},
                {f: True for f in shared}, {}, now, rescore)
            assert sum(r["answer_gain"] for r in rows) == sum(share.values()) == rescore(set(applied)) - now
            assert room == 100 - rescore(set(applied))
            # every answer listed for its own points went in
            assert {f for f in shared if gains[f][0] > 0} <= set(applied)


def test_the_shares_cost_a_bounded_number_of_probes():
    calls = {"n": 0}
    base = _floored(60.0, lambda f: 1.3 * len(f))

    def rescore(f):
        calls["n"] += 1
        return base(f)
    fields = ([SUB, RAD, USE] + EXTRA) * 4
    rows = [_row(f"{f}_{i}") for i, f in enumerate(fields)]
    _unify(rows, rescore, 60.0)
    assert calls["n"] <= S._MAX_PACKAGE_PROBES + S._MAX_SHARE_PROBES


# ── The real scorer ──────────────────────────────────────────────────────────
def _env(v):
    return {"value": v, "source": "producer", "confidence": "producer"}


def test_the_real_scorers_rows_add_up_to_answering_them_all():
    """18f6914f's shape: Exposure short a radius, Property short the hydrant and the
    fire department. The listed numbers are what answering all three makes."""
    facts = {k: _env("x") for k in list(S.TIER1_FIELDS) + list(S.TIER2_FIELDS)}
    facts.update({"applicant_name": _env("Acme LLC"), "effective_date": _env("01/01/2027"),
                  "expiration_date": _env("01/01/2028"), "contact_name": _env("Dana"),
                  "num_employees": _env("41"), "naics_code": _env("238210"),
                  "total_revenue": _env("$5,000,000"), "years_in_business": _env("17"),
                  "fein": _env("12-3456789"), "operations_description": _env("Electrical contractor"),
                  "auto_vin_schedule": _env([{"year": "2001", "make": "CHEVROLET"}]),
                  "auto_drivers": _env([{"name": "Marcus Delgado"}]),
                  "auto_garaging_addresses": _env(["Denver CO 80221"]),
                  "auto_vehicle_use": _env("service"), "auto_liability_limit": _env("$1,000,000"),
                  "auto_covered_symbols": _env("1"),
                  "locations": _env([{"address_line1": "4800 Washington St"}]),
                  "occupancy_type": _env("Office"), "construction_type": _env("Frame - wood construction"),
                  "property_building_value": _env("$500,000"), "year_built": _env("1999"),
                  "roof_year": _env("2015"), "sprinkler_system": _env("No - not sprinklered"),
                  "fire_protection_class": _env("Protection Class 3"),
                  "business_income_limit": _env("$250,000"), "period_of_restoration": _env("12 months"),
                  "wc_payroll": _env("$2,626,500"), "wc_class_codes": _env([{"code": "5190", "state": "CO"}]),
                  "wc_xmod": _env("1.08"), "wc_payroll_period": _env("Annual - the figure covers a full year"),
                  "wc_officer_exclusions": _env("No - all owners and officers are included")})
    flags = {"has_auto_coverage": True, "has_property_coverage": True, "has_workers_comp": True}
    kw = dict(flags=flags, form_results=[], cross_issues=[], hard_stops=[], soft_stops=[],
              session_data={"docs": []}, form_fill=False)
    pkg = S.calculate_package_sqs(facts=facts, **kw)
    rows = [r for r in pkg["top_recommendations"] if r.get("field")]
    shared = [r for r in rows if r.get("answer_gain_share")]
    assert {r["field"] for r in shared} >= {"loss_history_no_prior_losses_indicator", "distance_to_hydrant",
                                            "fire_department_type", "auto_radius_of_operation"}
    # prose cannot be probed: the narrative row carries no number of its own
    narrative = next(r for r in rows if r["pillar"] == "narrative_quality")
    assert "answer_gain" not in narrative and "answer_gain_share" not in narrative
    answered = dict(facts)
    for r in shared:
        answered[r["field"]] = S._package_probe_answer(r["field"])[0]
    after = S.calculate_package_sqs(facts=answered, **kw)
    total = after["raw_sqs_score"] - pkg["raw_sqs_score"]
    assert sum(r["answer_gain"] for r in shared) == total
    assert pkg["package_sqs_score"] + sum(r["answer_gain"] for r in shared) <= 100


# ── The page: whatever it works out itself stays inside 100 ──────────────────
def _node(tmp_path, body):
    script = tmp_path / "p.mjs"
    script.write_text(f"import * as R from {json.dumps(UTIL.as_uri())};\n{body}\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _share_row(field, gain, alone, exact=True, **extra):
    return {"pillar": "exposure_consistency", "score": 82, "field": field, "action": field,
            "answer_mode": "field", "answer_gain": gain, "answer_gain_alone": alone,
            "answer_gain_is_exact": exact, "answer_gain_share": True, "points_available": 2, **extra}


@needs_node
def test_the_page_prints_the_shares(tmp_path):
    pkg = {"package_sqs_score": 94, "top_recommendations": [
        _share_row(SUB, 3, 3), _share_row(RAD, 1, 2), _share_row(USE, 2, 2)]}
    o = _node(tmp_path, (
        f"const m = R.buildRecommendations({{ packageSqs: {json.dumps(pkg)}, formsExist: false }});\n"
        "console.log(JSON.stringify(m.score.map((i) => R.pointsText(i.points))));"))
    assert o == ["+3 pts", "+1 pts", "+2 pts"]


@needs_node
def test_a_share_of_zero_stays_listed_without_a_number(tmp_path):
    pkg = {"package_sqs_score": 90, "top_recommendations": [
        _share_row(SUB, 5, 5), _share_row(RAD, 0, 5), _share_row(USE, 0, 0, points_available=4)]}
    o = _node(tmp_path, (
        f"const m = R.buildRecommendations({{ packageSqs: {json.dumps(pkg)}, formsExist: false }});\n"
        "const s = m.score.map((i) => [i.detail, R.pointsText(i.points)]);\n"
        "const issue = R.scoreFixIssue(m.score[1]);\n"
        "console.log(JSON.stringify({ s, msg: issue.message }));"))
    # the row its neighbour answered is listed unnumbered; a row worth nothing at all is not
    assert o["s"] == [[SUB, "+5 pts"], [RAD, ""]]
    assert "Answering adds" not in o["msg"] and "+0" not in o["msg"]


@needs_node
def test_bounds_the_page_works_out_never_pass_100(tmp_path):
    # an older payload (no shares): each lone gain and the pillar bounds
    rows = [{"pillar": "exposure_consistency", "score": 82, "field": f, "action": f, "answer_mode": "field",
             "answer_gain": g, "answer_gain_is_exact": True, "points_available": 2}
            for f, g in ((SUB, 3), (RAD, 2), (USE, 2))]
    rows.append({"pillar": "property_integrity", "score": 90, "field": "distance_to_hydrant",
                 "action": "hydrant", "answer_mode": "field", "points_available": 4})
    pkg = {"package_sqs_score": 94, "top_recommendations": rows}
    o = _node(tmp_path, (
        f"const m = R.buildRecommendations({{ packageSqs: {json.dumps(pkg)}, formsExist: false }});\n"
        "console.log(JSON.stringify(m.score.map((i) => i.points)));"))
    assert sum(p["points"] for p in o) == 6
    assert o[0] == {"points": 3, "exact": True}
    assert o[2] == {"points": 1, "exact": False}       # cut to what was left: "up to"
    assert o[3] == {"points": 0, "exact": False}       # nothing left: listed, unnumbered


@needs_node
def test_a_held_row_with_a_share_names_its_gate_and_its_points(tmp_path):
    gate = _share_row("occupancy_type", 8, 8, pillar="property_integrity", score=0)
    held = _share_row("year_built", 3, 0, exact=False, pillar="property_integrity", score=0)
    nothing = _share_row("roof_year", 0, 0, pillar="property_integrity", score=0, points_available=5)
    pkg = {"package_sqs_score": 70, "top_recommendations": [gate, held, nothing]}
    o = _node(tmp_path, (
        f"const m = R.buildRecommendations({{ packageSqs: {json.dumps(pkg)}, formsExist: false }});\n"
        "console.log(JSON.stringify(m.score.map((i) => [i.detail, i.heldBy, R.pointsText(i.points)])));"))
    assert o == [["occupancy_type", None, "+8 pts"],
                 ["year_built", "occupancy_type", "up to +3 pts"],
                 ["roof_year", "occupancy_type", ""]]


# ── Review fixes (15 Oct 2026, the adversarial audit of the change above) ─────
def test_limits_are_probed_at_the_threshold_the_scorer_reads():
    # "50" passed every limit check and sat below every threshold: a row for a
    # MISSING underlying limit swapped "missing" for "below the minimum" and
    # measured nothing
    assert S._package_probe_answer("gl_each_occurrence") == (str(S._UMB_GL_OCC_MIN), True)
    assert S._package_probe_answer("gl_aggregate") == (str(S._UMB_GL_AGG_MIN), True)
    assert S._package_probe_answer("auto_liability_limit") == (str(S._UMB_AUTO_CSL_MIN), True)
    assert S._package_probe_answer("employers_liability_limits") == (str(S._UMB_EL_FULL), True)


def test_a_chain_that_ends_below_its_start_leaves_no_extra_room():
    # two answers that together cost more than the first one earns
    def effect(f):
        return (2 if SUB in f else 0) - (6 if (SUB in f and RAD in f) else 0) + (1 if RAD in f else 0)
    rescore = _floored(80.0, effect)
    gains = {SUB: (rescore({SUB}) - 80, True), RAD: (rescore({RAD}) - 80, True)}
    share, _base, room, applied = S._share_out_gains([SUB, RAD], [], gains, {SUB: "x", RAD: "x"},
                                                      {SUB: True, RAD: True}, {}, 80, rescore)
    assert sum(share.values()) == 0                   # the cost ate every share
    assert room == 100 - 80                           # never more room than the start left


@needs_node
def test_the_prerequisites_of_a_pillar_held_at_0_stay_listed(tmp_path):
    # occupancy AND construction AND a value: none lifts the COPE minimum alone,
    # so the chain gives the last one the whole unlock and the others 0
    rows = [_share_row("occupancy_type", 0, 0, pillar="property_integrity", score=0, points_available=5),
            _share_row("construction_type", 0, 0, pillar="property_integrity", score=0, points_available=5),
            _share_row("property_building_value", 9, 0, exact=False, pillar="property_integrity", score=0)]
    pkg = {"package_sqs_score": 60, "top_recommendations": rows}
    o = _node(tmp_path, (
        f"const m = R.buildRecommendations({{ packageSqs: {json.dumps(pkg)}, formsExist: false }});\n"
        "console.log(JSON.stringify(m.score.map((i) => [i.detail, R.pointsText(i.points)])));"))
    assert o == [["occupancy_type", ""], ["construction_type", ""], ["property_building_value", "up to +9 pts"]]



def test_a_stated_limit_is_never_probed_up_to_the_threshold():
    # a TRUE limit below the umbrella minimum is a coverage finding: its row must
    # not promise points for typing a bigger limit than the policy has
    assert S._package_probe_answer("gl_each_occurrence", stated=True) != (str(S._UMB_GL_OCC_MIN), True)
    facts = {"umbrella_limit": {"value": "5000000"}, "gl_each_occurrence": {"value": "500000"},
             "gl_aggregate": {"value": "2000000"},
             "schedule_of_underlying_insurance": {"value": "General Liability $500,000"},
             "umbrella_follow_form": {"value": "Follows form - explicitly stated in the submitted documents"}}
    rows = [_row("gl_each_occurrence", "umbrella_limit_adequacy", 80)]
    calls = []

    def rescore(f):
        calls.append(f.get("gl_each_occurrence"))
        return 90
    S._unify_card_points([], rows, facts, 90, None, lambda _c: None, rescore)
    assert str(S._UMB_GL_OCC_MIN) not in [str(c) for c in calls]


# ── Every number on the first screen adds up to 100 - score (owner, 15 Oct) ──
# A table card (the COPE hard stop, the driver schedule) hides the rows it opens;
# their points sit on that card. A cap share for a code the page does not draw
# goes to the cards it does draw. Live shape: 8a61a2a6 (score 40) printed 47 of
# 60 before this - the COPE card and the driver card printed nothing.
@needs_node
def test_cards_details_and_rows_add_up_to_what_is_missing(tmp_path):
    sp = UTIL.with_name("screenPoints.js").as_uri()
    kc = UTIL.with_name("keyDetailCards.js").as_uri()
    pkg = {
        "package_sqs_score": 62,
        "screen_shares": {"occupancy_type": [10, True], "mailing_address": [2, True], "fein": [2, True],
                          "auto_drivers": [2, True], "year_built": [1, True],
                          "loss_history_no_prior_losses_indicator": [12, True],
                          "additional_remarks_text": [5, True]},
        "screen_card_points": {"legacy_minimum_viable_cope": [1, False],
                               "tier1_missing_Applicant mailing address": [1, False],
                               "a_rule_the_page_does_not_draw": [2, False]},
        "screen_unanswerable": [],
        "top_recommendations": [
            _share_row("mailing_address", 2, 2, pillar="structural_completeness"),
            _share_row("occupancy_type", 10, 10, pillar="property_integrity"),
            _share_row("year_built", 1, 1, pillar="property_integrity"),
            _share_row("auto_drivers", 2, 2, answer_mode="schedule", schedule_key="auto_drivers"),
            _share_row("loss_history_no_prior_losses_indicator", 12, 12, pillar="loss_history_alignment"),
            _share_row("additional_remarks_text", 5, 5, pillar="narrative_quality", answer_mode="narrative"),
        ]}
    grouped = {
        "hard_stops": [{"items": [{"code": "legacy_minimum_viable_cope", "resolution": {
            "mode": "schedule", "schedule_key": "property_locations",
            "columns": ["construction_type", "building_value"], "facts": ["occupancy_type"]}}]}],
        "warnings": {
            "required": [{"items": [{"code": "tier1_missing_Applicant mailing address",
                                     "resolution": {"mode": "field", "facts": ["mailing_address"]}}]}],
            "recommended": [{"items": [{"code": "legacy_auto_driver_schedule_missing",
                                        "resolution": {"mode": "schedule", "schedule_key": "auto_drivers"}}]}]}}
    kd = {"missing": ["Applicant mailing address", "FEIN / Tax ID"], "missing_items": [
        {"label": "Applicant mailing address", "facts": ["mailing_address"],
         "resolution": {"mode": "field", "facts": ["mailing_address"]}},
        {"label": "FEIN / Tax ID", "facts": ["fein"], "resolution": {"mode": "field", "facts": ["fein"]}}]}
    o = _node(tmp_path, (
        f"const P = await import({json.dumps(sp)});\nconst K = await import({json.dumps(kc)});\n"
        f"const g = {json.dumps(grouped)};\nconst p = {json.dumps(pkg)};\n"
        f"const kd = K.withKeyDetailCards({json.dumps(kd)}, g);\n"
        "const m = R.buildRecommendations({ packageSqs: p, groupedIssues: g, keyDetails: kd, formsExist: false });\n"
        "const s = P.screenPoints(p, g, kd);\n"
        "console.log(JSON.stringify({ rows: m.score.map((i) => [i.fact || i.field || i.id, i.points ? i.points.points : 0]),\n"
        "  cards: [...s.cards], details: [...s.details], un: s.unanswerable }));"))
    cards = {k: v["points"] for k, v in o["cards"]}
    assert cards == {"legacy_minimum_viable_cope": 12, "tier1_missing_Applicant mailing address": 4,
                     "legacy_auto_driver_schedule_missing": 2}
    assert {k: v["points"] for k, v in o["details"]} == {"FEIN / Tax ID": 2}
    total = (sum(cards.values()) + sum(v["points"] for _k, v in o["details"])
             + sum(n for _f, n in o["rows"]) + sum(u["points"] for u in o["un"]))
    assert total == 100 - pkg["package_sqs_score"]


# ── A document disagreement's points sit where it is fixed (15 Oct) ──────────
# Its Data Consistency row ("Values to confirm"), or the card whose "Fix in Data
# Consistency" button leads there - never spread onto unrelated cards.
@needs_node
def test_a_document_disagreement_prints_its_points_where_it_is_fixed(tmp_path):
    sp = UTIL.with_name("screenPoints.js").as_uri()
    pkg = {"package_sqs_score": 90,
           "screen_shares": {"mailing_address": [4, True]},
           "screen_card_points": {"tier1_missing_Applicant mailing address": [2, False]},
           "screen_dc_points": {"policy_number": [2, False], "fein": [2, False]},
           "screen_unanswerable": [],
           "top_recommendations": [_share_row("mailing_address", 4, 4, pillar="structural_completeness")]}
    grouped = {"hard_stops": [{"items": [{"code": "doc_conflict_hard_fein_conflict", "resolution": {"mode": "none"}}]}],
               "warnings": {"required": [{"items": [{"code": "tier1_missing_Applicant mailing address",
                                                    "resolution": {"mode": "field", "facts": ["mailing_address"]}}]}]}}
    o = _node(tmp_path, (
        f"const P = await import({json.dumps(sp)});\n"
        f"const p = {json.dumps(pkg)};\nconst g = {json.dumps(grouped)};\n"
        "const s = P.screenPoints(p, g, null, new Set(['policy_number', 'fein']));\n"
        "const m = R.buildRecommendations({ packageSqs: p, groupedIssues: g, formsExist: false });\n"
        "console.log(JSON.stringify({ cards: [...s.cards], dc: [...s.dc], un: s.unanswerable,\n"
        "  rows: m.score.map((i) => i.points ? i.points.points : 0) }));"))
    cards = {k: v["points"] for k, v in o["cards"]}
    # Every open row prints its own share; FEIN's card leads to its row and shows
    # the SAME number (a mirror, counted once).
    assert {k: v["points"] for k, v in o["dc"]} == {"policy_number": 2, "fein": 2}
    assert cards == {"doc_conflict_hard_fein_conflict": 2, "tier1_missing_Applicant mailing address": 6}
    assert dict((k, v["mirror"]) for k, v in o["cards"])["doc_conflict_hard_fein_conflict"] == 2
    assert o["un"] == []
    own = sum(v["points"] - v["mirror"] for _k, v in o["cards"])
    assert own + 4 + sum(o["rows"]) == 100 - pkg["package_sqs_score"]


def test_a_picker_conflict_stop_is_keyed_by_its_row():
    from services.stops_now import conflict_stop_facts, underwriting_conflict_stops
    uw = {"review_required": True, "fields": [{"fact_key": "policy_number", "label": "Policy Number",
          "review_required": True, "values": [{"display": "A-1"}, {"display": "B-2"}]}]}
    (key, msg, _blocking), = underwriting_conflict_stops(uw, {})
    assert conflict_stop_facts({"underwriting_consistency": uw, "flags": {}, "docs": []}) == {msg: "policy_number"}


# ── No warning that costs points ships without a fix button (15 Oct) ─────────
# A card's fix is "Open to fix" (a box, a table, an explanation), "Fix in Data
# Consistency" (a conflict code) or "Add ACORD xx" (`add_forms` at its emit site).
def test_every_rule_that_costs_points_has_a_fix_button():
    import re
    import services.issue_registry as IR
    src = (pathlib.Path(__file__).resolve().parents[1] / "services" / "cross_form_validator.py").read_text(encoding="utf-8")

    def call_text(start):                                  # the whole _issue(...) call
        depth = 0
        for i in range(start, len(src)):
            if src[i] == "(":
                depth += 1
            elif src[i] == ")":
                depth -= 1
                if depth == 0:
                    return src[start:i + 1]
        return src[start:]

    fix = {"field", "schedule", "narrative"}
    calls = list(re.finditer(r'_issue\(\s*"(hard_stop|soft_warning|advisory)"\s*,\s*"([a-z0-9_]+)"', src))
    costs = {m.group(2) for m in calls if m.group(1) in ("hard_stop", "soft_warning")}
    assert len(costs) > 20                                   # the harvest found the rules
    no_button = []
    for code in sorted(costs):
        if (IR.resolution_for(code) or {}).get("mode") in fix:
            continue
        if not all("add_forms=" in call_text(m.start()) for m in calls if m.group(2) == code):
            no_button.append(code)
    assert not no_button, f"these rules cost points and offer no fix button: {no_button}"
    legacy = {r[3] for r in IR._LEGACY_MESSAGE_RULES
              if not isinstance(r[4], dict) or r[4].get("mode") not in fix}
    # The Tier 1 backstop fires only on a field label the code does not know.
    assert legacy <= {"legacy_tier1_unrecognised_field"}, legacy


# ── The answer box takes only what the later check accepts (15 Oct) ───────────
def test_the_box_takes_only_what_the_later_check_accepts_and_the_shape_stays():
    import services.extraction_service as es
    from services.fact_registry import FACT_REGISTRY, answer_check, _is_phone
    phone = answer_check(FACT_REGISTRY["contact_phone"])
    assert phone("303-996-7800 x12") and not phone("996-7800")
    assert answer_check(FACT_REGISTRY["naics_code"])("238160")
    assert not answer_check(FACT_REGISTRY["naics_code"])("998877")
    # The fact's SHAPE is untouched, so extraction is too: the merge still ranks a
    # phone over a name for contact_phone.
    assert FACT_REGISTRY["contact_phone"]["validate"] is _is_phone
    assert "contact_phone" in es._hard_shape_facts()
