"""Z38 lane E (24 Oct 2026): the review plan answers only the empty boxes; a loss
run counts only its years inside the last min(5, age) years; a stale half of the
ACORD 160 earthquake deductible pair written by a PRODUCER card answer is cleared
by a later answer, never a box the producer typed in the editor."""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import arq_service as arq                                 # noqa: E402
from services import review_plan as rp                                  # noqa: E402
from services.loss_history_state import (                               # noqa: E402
    loss_run_coverage, loss_window_start, years_inside_window)
from services.sqs_service import _resolve_loss_history_years             # noqa: E402


# ── 1. the plan types only the empty boxes ───────────────────────────────────

class _FakeSim:
    def __init__(self, facts):
        self.session = {"facts": facts}
        self.answered = []

    def answer(self, fact, value):
        self.answered.append(fact)
        return True


def _env(v):
    return {"value": v, "source": "ai", "value_state": "present"}


def test_a_card_probes_only_its_empty_boxes():
    """Live 3e835b53: the Carrier-Grade COPE card's window shows the stated
    coinsurance (80%) and valuation; probing them raised a warning a person's
    save never raises, so the card showed +1 and moved +3."""
    sim = _FakeSim({"coinsurance_percentage": _env("80%"), "valuation_method": _env("RCV")})
    item = {"kind": "card", "resolution": {"mode": "field", "facts": [
        "year_built", "roof_year", "valuation_method", "coinsurance_percentage"]}}
    assert rp._apply(sim, item, {}, 5) is True
    assert sim.answered == ["year_built", "roof_year"]


def test_a_card_about_a_wrong_stated_value_still_probes_it():
    """Every box stated (a card about a WRONG value): all are probed, as before."""
    sim = _FakeSim({"coinsurance_percentage": _env("50%")})
    item = {"kind": "card", "resolution": {"mode": "field", "facts": ["coinsurance_percentage"]}}
    assert rp._apply(sim, item, {}, 5) is True
    assert sim.answered == ["coinsurance_percentage"]


def test_a_person_none_answer_counts_as_answered():
    sim = _FakeSim({"distance_to_hydrant": {"value": None, "source": "producer",
                                            "value_state": "not_applicable"}})
    item = {"kind": "rec", "resolution": {"mode": "field", "facts": [
        "distance_to_hydrant", "fire_department_type"]}}
    rp._apply(sim, item, {}, 5)
    assert sim.answered == ["fire_department_type"]


# ── 2. only the years inside the window count ────────────────────────────────

TODAY = date(2026, 10, 24)


def _run(a, b, **extra):
    return {"loss_run_period_start": a, "loss_run_period_end": b, **extra}


def test_the_window_opens_required_years_before_today_less_the_grace():
    assert loss_window_start({}, TODAY) == date(2021, 7, 26)
    assert loss_window_start({"years_in_business": "3"}, TODAY) == date(2023, 7, 26)


def test_the_window_ends_at_a_recent_past_effective_date():
    f = {"effective_date": "07/15/2026"}
    assert loss_window_start(f, TODAY) == date(2021, 4, 16)
    # a stale effective more than a year back is ignored
    assert loss_window_start({"effective_date": "01/01/2024"}, TODAY) == date(2021, 7, 26)
    # a future effective is never the anchor (a fresh run is never cut by it)
    assert loss_window_start({"effective_date": "07/15/2027"}, TODAY) == date(2021, 7, 26)


@pytest.mark.parametrize("a,b,expected", [
    (date(2019, 1, 1), date(2021, 6, 30), 0),     # wholly outside
    (date(2019, 1, 1), date(2021, 12, 31), 0),    # 5 months inside rounds to 0
    (date(2019, 1, 1), date(2024, 1, 1), 2),      # only the inside part
    (date(2021, 10, 1), date(2026, 10, 1), None),  # wholly inside: the caller's own count
])
def test_years_inside_window(a, b, expected):
    assert years_inside_window(a, b, {}, TODAY) == expected


def test_a_2019_2021_run_alone_covers_nothing():
    assert _resolve_loss_history_years(_run("01/01/2019", "06/30/2021")) == 0
    docs = [{"doc_type": "loss_run", "doc_id": "old", "facts": _run("01/01/2019", "06/30/2021")}]
    cov = loss_run_coverage(docs, _run("01/01/2019", "06/30/2021"))
    assert cov["covered"] == 0
    assert cov["documents"][0]["outside_window"] is True
    assert "outside the years that count" in cov["documents"][0]["years_label"]


def test_a_current_five_year_run_still_counts_five():
    assert _resolve_loss_history_years(_run("10/01/2021", "10/01/2026")) == 5
    # valued six months ago: the grace keeps it at 5
    assert _resolve_loss_history_years(_run("04/01/2021", "04/01/2026")) == 5


def test_a_young_business_window_is_its_age():
    f = _run("01/01/2019", "10/01/2026", years_in_business="3")
    assert _resolve_loss_history_years(f) == 3


def test_an_undated_count_is_unchanged():
    assert _resolve_loss_history_years({"loss_history_years": "4"}) == 4


# ── 3. the stale half a producer CARD answer wrote is cleared ────────────────

def _quake():
    from tests.test_build24_percent_review_b import EQ_AMOUNT, EQ_PERCENT, QUAKE, _generated, _pair
    return EQ_AMOUNT, EQ_PERCENT, QUAKE, _generated, _pair


def test_a_card_answer_records_the_box_and_a_later_answer_clears_its_stale_half():
    EQ_AMOUNT, EQ_PERCENT, QUAKE, _generated, _pair = _quake()
    facts = {"applicant_name": "Acme LLC"}
    gen = {"ACORD_160": _generated("ACORD_160", facts)}
    first = {**facts, QUAKE: {"value": "2%", "source": "producer"}}
    arq._restamp_canonical_into_forms(gen, QUAKE, first, provenance="producer")
    form = gen["ACORD_160"]
    assert _pair(form["field_state"]) == ("", "2")
    assert EQ_PERCENT in arq.answer_written_boxes(form)
    second = {**facts, QUAKE: {"value": "$25,000", "source": "producer"}}
    arq._restamp_canonical_into_forms(gen, QUAKE, second, provenance="producer")
    assert _pair(form["field_state"]) == ("25,000", "")
    assert EQ_PERCENT not in form["confidence"]
    assert arq.answer_written_boxes(form) == {EQ_AMOUNT}


def test_a_box_the_producer_typed_in_the_editor_is_never_cleared():
    from routes.form_routes import label_producer_edits
    EQ_AMOUNT, EQ_PERCENT, QUAKE, _generated, _pair = _quake()
    facts = {"applicant_name": "Acme LLC"}
    gen = {"ACORD_160": _generated("ACORD_160", facts)}
    form = gen["ACORD_160"]
    # a card answer wrote the percent box ...
    arq._restamp_canonical_into_forms(gen, QUAKE, {**facts, QUAKE: {"value": "2%", "source": "producer"}},
                                      provenance="producer")
    # ... then the producer typed over it in the editor
    written = arq.answer_written_boxes(form)
    form["field_state"][EQ_PERCENT] = "3"
    label_producer_edits(form["confidence"], set(), {EQ_PERCENT: "3"}, written)
    form[arq.ANSWER_WRITTEN_KEY] = sorted(written)
    assert EQ_PERCENT not in arq.answer_written_boxes(form)
    arq._restamp_canonical_into_forms(gen, QUAKE, {**facts, QUAKE: {"value": "$25,000", "source": "producer"}},
                                      provenance="producer")
    assert _pair(form["field_state"]) == ("25,000", "3")
    assert form["confidence"][EQ_PERCENT] == "producer"


def test_a_producer_box_with_no_record_stays():
    """An old form (no record) keeps the Z37 rule: a producer box stays."""
    EQ_AMOUNT, EQ_PERCENT, QUAKE, _generated, _pair = _quake()
    facts = {"applicant_name": "Acme LLC"}
    gen = {"ACORD_160": _generated("ACORD_160", facts)}
    gen["ACORD_160"]["field_state"][EQ_AMOUNT] = "25,000"
    gen["ACORD_160"]["confidence"][EQ_AMOUNT] = "producer"
    arq._restamp_canonical_into_forms(gen, QUAKE, {**facts, QUAKE: {"value": "2%", "source": "producer"}},
                                      provenance="producer")
    assert _pair(gen["ACORD_160"]["field_state"]) == ("25,000", "2")


def test_the_editor_label_helper_keeps_its_old_signature():
    from routes.form_routes import label_producer_edits
    conf = {}
    label_producer_edits(conf, set(), {"X": "1"})
    assert conf == {"X": "producer"}


def test_a_run_wholly_outside_scores_as_no_run_never_the_unreadable_60():
    from services.sqs_service import calculate_p4_loss_history as p4
    base = {"years_in_business": {"value": "15"}, "num_claims": {"value": "0"}}

    def score(a, b):
        f = dict(base, loss_run_period_start={"value": a}, loss_run_period_end={"value": b},
                 loss_run_valuation_date={"value": b})
        return p4(f, {}, True, "strong")

    outside, recs = score("01/01/2019", "06/30/2021")
    partial, _ = score("01/01/2019", "01/01/2024")
    full, _ = score("10/01/2021", "10/01/2026")
    assert outside < partial < full
    assert outside != 60 and any("only years before the last 5" in r for r in recs)
