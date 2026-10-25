"""Several loss-run documents cover the years together (owner, 24 Oct 2026)."""
from services.loss_history_state import combine_loss_run_periods


def _doc(a, b, excluded=False, kind="loss_run"):
    return {"doc_type": kind, "excluded": excluded,
            "facts": {"loss_run_period_start": a, "loss_run_period_end": b}}


def _period(f):
    return f["loss_run_period_start"]["value"], f["loss_run_period_end"]["value"]


def test_two_runs_back_to_back_cover_five_years():
    f = {"loss_run_period_start": "01/01/2025", "loss_run_period_end": "01/01/2026"}
    assert combine_loss_run_periods(f, [_doc("01/01/2025", "01/01/2026"), _doc("01/01/2021", "01/01/2025")])
    assert _period(f) == ("01/01/2021", "01/01/2026")


def test_a_gap_is_never_joined_the_latest_stretch_counts():
    f = {}
    combine_loss_run_periods(f, [_doc("01/01/2025", "01/01/2026"), _doc("01/01/2019", "01/01/2022")])
    assert _period(f) == ("01/01/2025", "01/01/2026")


def test_excluded_and_non_loss_run_documents_do_not_count():
    f = {"loss_run_period_start": "01/01/2025", "loss_run_period_end": "01/01/2026"}
    assert not combine_loss_run_periods(f, [_doc("01/01/2025", "01/01/2026"),
                                            _doc("01/01/2021", "01/01/2025", excluded=True)])
    assert not combine_loss_run_periods(f, [_doc("01/01/2025", "01/01/2026"),
                                            _doc("01/01/2021", "01/01/2025", kind="dec_page")])


def test_one_run_or_a_typed_period_is_left_alone():
    f = {"loss_run_period_start": "01/01/2025", "loss_run_period_end": "01/01/2026"}
    assert not combine_loss_run_periods(f, [_doc("01/01/2021", "01/01/2026")])
    typed = {"loss_run_period_start": {"value": "01/01/2024", "source": "producer"},
             "loss_run_period_end": {"value": "01/01/2026", "source": "producer"}}
    assert not combine_loss_run_periods(typed, [_doc("01/01/2025", "01/01/2026"), _doc("01/01/2021", "01/01/2025")])
