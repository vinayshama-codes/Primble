"""Late hostile review, 29 Oct 2026: cap shares, the truncated-VIN fold and the
transcriber page budget."""
import asyncio
import inspect
import os

os.environ.setdefault("NARRATIVE_READER", "0")

from services import review_plan as RP
from services.acord_intake import merge_rules as MR
from services.acord_intake import transcriber_intake as TI


def _it(i, gain=0.0, own=0.0, pts=0, held=None, cleared=(), released=(), kind="card"):
    return {"id": i, "kind": kind, "gain": gain, "_own": own, "points": pts, "held_by": held,
            "_cleared": list(cleared), "_released": list(released), "_did": True}


# ── cap shares ────────────────────────────────────────────────────────────────
def test_holders_listed_below_the_releasing_step_keep_their_share():
    """The step that lifts the 85 is first on the page; the two warnings it
    shares with come below it. Their shares were wiped (`f[id] = ...`)."""
    items = [_it("w0", gain=9, pts=9, cleared=["soft"], released=["soft"]),
             _it("w1", cleared=["soft"]), _it("w2", cleared=["soft"])]
    RP._share_group_releases(items, 9, {"soft": 3})
    RP._no_listed_zero(items, None)
    assert [x["points"] for x in items] == [3, 3, 3]


def test_an_item_holding_two_holds_shares_both_releases_in_one_pool():
    items = [_it("w1", cleared=["soft"]), _it("w2", gain=4, pts=4, cleared=["soft"], released=["soft"]),
             _it("h1", cleared=["hard", "soft"]), _it("h2", gain=10, pts=10, cleared=["hard"], released=["hard"])]
    RP._share_group_releases(items, 14, {"hard": 2, "soft": 2})
    RP._no_listed_zero(items, None)
    p = {x["id"]: x["points"] for x in items}
    assert sum(p.values()) == 14 and min(p.values()) >= 1
    assert abs(p["h1"] - (4 / 3 + 5)) < 1 and abs(p["h2"] - 5) < 1     # h2 shares with h1
    assert all("hard stops and warnings" in x["with_others"] for x in items)


def test_any_step_records_the_hold_it_releases_not_only_a_card():
    """A key detail / row whose answer lifts the last 60 named "hard" in
    `_released`; it was computed inside the card-only branch, so the hard-stop
    cards it shares with got nothing and the wording said "warnings"."""
    src = inspect.getsource(RP.build_review_plan)
    line = next(ln for ln in src.splitlines() if 'it["_released"] = rel' in ln)
    card = next(ln for ln in src.splitlines() if 'if it.get("kind") == "card" and it.get("message")' in ln)
    assert len(line) - len(line.lstrip()) == len(card) - len(card.lstrip())


def test_a_non_card_step_releasing_the_hard_hold_shares_with_hard_stops():
    items = [_it("h1", cleared=["hard"]), _it("r", gain=10, pts=10, cleared=["hard"],
                                              released=["hard"], kind="rec")]
    RP._share_group_releases(items, 10, {"hard": 2})
    RP._no_listed_zero(items, None)
    assert [x["points"] for x in items] == [5, 5]
    assert items[0]["with_others"] == "counts when all 2 hard stops are fixed"


# ── truncated VIN ─────────────────────────────────────────────────────────────
A, B = "1GCWGAFP8K1234561", "1GCWGAFP8K1234562"


def _v(vin):
    return {"vin": vin, "year": "2019", "make": "Chevrolet", "model": "Express"}


def test_a_short_vin_two_full_vins_start_with_joins_neither_in_any_order():
    assert len(MR.fold_rows("auto_vin_schedule", [[_v(A), _v(B)], [_v(A[:16])]])) == 3
    assert len(MR.fold_rows("auto_vin_schedule", [[_v(A[:16])], [_v(A), _v(B)]])) == 3


def test_a_short_vin_takes_its_full_vin_whatever_comes_first():
    rows = MR.fold_rows("auto_vin_schedule", [[_v(A[:15])], [_v(A)]])
    assert len(rows) == 1 and rows[0]["vin"] == A
    rows = MR.fold_rows("auto_vin_schedule", [[_v(A)], [_v(A[:15])]])
    assert len(rows) == 1 and rows[0]["vin"] == A


def test_a_short_vin_in_an_envelope_with_dashes_and_lowercase():
    rows = MR.fold_rows("auto_vin_schedule", [[_v("1gcw-gafp 8k12345")], [_v({"value": A})]])
    assert len(rows) == 1
    # a third copy of the full VIN still joins the same vehicle
    assert len(MR.fold_rows("auto_vin_schedule", [[_v(A[:15])], [_v(A)], [_v(A)]])) == 1


def test_two_full_vins_one_apart_stay_two():
    assert len(MR.fold_rows("auto_vin_schedule", [[_v(A)], [_v(B)]])) == 2


# ── page budget ───────────────────────────────────────────────────────────────
class _Cfg:
    live = True
    max_pages_per_package = 40


def test_add_documents_opens_a_fresh_budget(monkeypatch):
    monkeypatch.setattr(TI, "load_config", lambda: _Cfg())
    TI._PACKAGE_BUDGET.set({"left": 0})          # an old package's spent budget
    TI.open_package_budget()
    assert TI._PACKAGE_BUDGET.get() == {"left": 40}
    assert TI._spend(30) and not TI._spend(20)


def test_not_live_opens_no_budget(monkeypatch):
    class _Off(_Cfg):
        live = False
    monkeypatch.setattr(TI, "load_config", lambda: _Off())
    TI._PACKAGE_BUDGET.set({"left": 0})
    TI.open_package_budget()
    assert TI._PACKAGE_BUDGET.get() is None
    src = inspect.getsource(TI.presubmit_package)
    assert src.index("open_package_budget()") < src.index("return 0")


def test_the_add_documents_route_opens_the_budget():
    from routes import session_documents_routes as R
    src = inspect.getsource(R.add_session_documents)
    assert "open_package_budget()" in src


def test_a_failed_presubmit_gives_its_pages_back(monkeypatch):
    src = inspect.getsource(TI.presubmit_package)
    assert "_refund(len(group.pages))" in src
    TI._PACKAGE_BUDGET.set({"left": 10})
    assert TI._spend(4)
    TI._refund(4)
    assert TI._PACKAGE_BUDGET.get() == {"left": 10}
