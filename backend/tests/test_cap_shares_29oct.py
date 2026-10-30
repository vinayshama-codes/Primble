"""Cap shares (owner, 29 Oct 2026): every item a person must solve to reach 100
shows a number, several holders of one hold share its release evenly, and the
numbers add up to exactly 100 - score. `services/review_plan._share_group_releases`."""
import os
import pickle
import random

import pytest

os.environ.setdefault("NARRATIVE_READER", "0")

from services import review_plan as RP
import reach100_harness as H

PKL = "/private/tmp/claude-501/-Users-vinaysharma-Downloads-Primble-16thsep/427f82bb-424b-4678-bf06-9112a9013561/scratchpad"


def _it(i, gain=0.0, own=0.0, pts=0, held=None, cleared=(), released=(), kind="card"):
    return {"id": i, "kind": kind, "gain": gain, "_own": own, "points": pts, "held_by": held,
            "_cleared": list(cleared), "_released": list(released), "_did": True}


def _shown(items):
    return [it for it in items if not it.get("mirror_of")]


def test_several_holders_share_the_release_evenly():
    items = [_it("a", cleared=["soft"]), _it("b", cleared=["soft"]), _it("c", cleared=["soft"]),
             _it("d", gain=6.0, own=0.0, pts=6, cleared=["soft"], released=["soft"])]
    RP._share_group_releases(items, 6, {"soft": 4})
    pts = [it["points"] for it in items]
    assert sum(pts) == 6 and min(pts) >= 1 and max(pts) - min(pts) <= 1
    assert all("counts when all 4 warnings are fixed" == it["with_others"] for it in items)
    assert all(it["held_by"] is None for it in items)


def test_own_gain_is_kept_and_withheld_gain_paid_back():
    items = [_it("a", own=3.0, held="X", cleared=["soft"]), _it("b", cleared=["soft"]),
             _it("c", gain=7.0, own=0.0, pts=7, cleared=["soft"], released=["soft"])]
    RP._share_group_releases(items, 7, {"soft": 3})
    a, b, c = (it["points"] for it in items)
    assert a + b + c == 7 and a >= 4 and b >= 1 and c >= 1


def test_mixed_hard_stops_and_warnings():
    items = [_it("h1", cleared=["hard"]), _it("h2", gain=10.0, pts=10, cleared=["hard"], released=["hard"]),
             _it("w1", cleared=["soft"]), _it("w2", gain=5.0, pts=5, cleared=["soft"], released=["soft"])]
    RP._share_group_releases(items, 15, {"hard": 2, "soft": 2})
    p = {it["id"]: it["points"] for it in items}
    assert p["h1"] + p["h2"] == 10 and p["w1"] + p["w2"] == 5
    assert min(p.values()) >= 1
    assert "hard stops" in items[0]["with_others"] and "warnings" in items[2]["with_others"]


def test_a_single_holder_gets_the_whole_release():
    """One warning left at 90 shows +10."""
    items = [_it("w", gain=10.0, own=0.0, pts=10, cleared=["soft"], released=["soft"])]
    RP._share_group_releases(items, 10, {"soft": 1})
    RP._no_listed_zero(items, None)
    assert items[0]["points"] == 10 and not items[0].get("with_others")


def test_an_item_that_moves_nothing_is_not_a_score_item():
    items = [_it("x"), _it("y", gain=2.0, own=2.0, pts=2)]
    items[0]["_cleared"] = []
    RP._no_listed_zero(items, None)
    assert items[0]["score_item"] is False and items[0]["points"] == 0
    assert items[1]["points"] == 2


def _check(pkg):
    probs = H.plan_problems(pkg)
    plan = pkg.get("review_plan") or {}
    for it in plan.get("items") or []:
        if it.get("mirror_of") or it.get("score_item") is False:
            continue
        # P1 (SCORING_RULES.md): a number, or "under 1 pt" when whole points
        # cannot go round - never a point borrowed from another item (29 Oct
        # 2026: the borrow broke P3, each item keeping its own gain).
        if int(it.get("points") or 0) <= 0 and not it.get("under") and pkg.get("package_sqs_score", 100) < 100:
            probs.append(f"listed at 0: {it.get('id')}")
        if it.get("held_by") and int(it.get("points") or 0) <= 0:
            probs.append(f"counts once with no number: {it.get('id')}")
    return probs


def _stored():
    out = []
    p = os.path.join(PKL, "rv", "sess29.pkl")
    if os.path.exists(p):
        out += list(pickle.load(open(p, "rb")).items())
    p = os.path.join(PKL, "cap", "cd68.pkl")
    if os.path.exists(p):
        out.append(("cd683556", pickle.load(open(p, "rb"))))
    return out


@pytest.mark.parametrize("name,row", _stored() or [pytest.param("none", None, marks=pytest.mark.skip)])
def test_stored_packages_add_up_with_no_zero_item(name, row):
    pkg, _kd, _items = H.read_page(row)
    assert _check(pkg) == []


def test_cd683556_warnings_each_show_a_number():
    rows = dict(_stored())
    if "cd683556" not in rows:
        pytest.skip("cd683556 not pickled")
    pkg, _kd, _items = H.read_page(rows["cd683556"])
    items = {it["code"]: it for it in pkg["review_plan"]["items"] if it.get("kind") == "card"}
    for code in ("doc_conflict_warn_date_conflict", "bi_missing_period_of_restoration",
                 "per_location_cope_incomplete", "legacy_wc_monopolistic_state"):
        # A card whose sentence still holds the 85 shows a number or "under 1 pt"
        # with its condition; one the stops no longer raise (29 Oct evening: the
        # COPE / monopolistic sentences left the soft stops in the underwriting
        # review) holds nothing and reads "No effect on the score" (P5).
        # End-user review (29 Oct night, TEST updated): a stored card the stops
        # no longer raise is not drawn at all (`issue_registry.
        # structured_as_they_stand`) - P5's "or is not listed".
        it = items.get(code)
        if it is None:
            assert code != "bi_missing_period_of_restoration"
            continue
        assert ((it["points"] >= 1 or it.get("under")) and "counts when all" in it["with_others"]) \
            or (it.get("score_item") is False and not it["points"]), (code, it)
    if "acord101_required" in items:
        assert items["acord101_required"].get("mirror_of") or items["acord101_required"]["points"] >= 1
    if "loss_history_attestation_conflict" in items:
        assert items["loss_history_attestation_conflict"]["score_item"] is False


@pytest.mark.parametrize("seed", range(10))
@pytest.mark.parametrize("gen", ["synthetic", "wider"])
def test_random_packages_show_no_zero_item(seed, gen):
    rnd = random.Random(seed * 7 + (0 if gen == "synthetic" else 1))
    row = H.synthetic_package(rnd) if gen == "synthetic" else H.wider_package(rnd)
    pkg, _kd, _items = H.read_page(row)
    assert _check(pkg) == []
