"""Live run 6875e80c (30 Oct 2026): a 2024-valued run plus a 2026-valued run kept the
2024 date, so the history read as stale. The newest included run's date wins."""
from services.loss_history_state import latest_loss_run_valuation


def _doc(val, excluded=False, doc_type="loss_run"):
    return {"doc_type": doc_type, "excluded": excluded, "facts": {"loss_run_valuation_date": val}}


def test_newest_run_decides():
    f = {"loss_run_valuation_date": {"value": "01/10/2024"}}
    assert latest_loss_run_valuation(f, [_doc("01/10/2024"), _doc("10/20/2026")])
    assert f["loss_run_valuation_date"]["value"] == "10/20/2026"


def test_order_does_not_matter_and_no_change_when_already_newest():
    f = {"loss_run_valuation_date": "10/20/2026"}
    assert not latest_loss_run_valuation(f, [_doc("10/20/2026"), _doc("01/10/2024")])
    assert f["loss_run_valuation_date"] == "10/20/2026"


def test_excluded_and_non_loss_run_documents_never_count():
    f = {"loss_run_valuation_date": "01/10/2024"}
    assert not latest_loss_run_valuation(f, [_doc("01/10/2024"), _doc("10/20/2026", excluded=True),
                                             _doc("10/25/2026", doc_type="dec_page")])
    assert f["loss_run_valuation_date"] == "01/10/2024"


def test_person_typed_date_is_kept():
    f = {"loss_run_valuation_date": {"value": "05/01/2025", "source": "producer"}}
    latest_loss_run_valuation(f, [_doc("10/20/2026")])
    assert f["loss_run_valuation_date"]["value"] in ("05/01/2025", "10/20/2026")
    from services.fact_state import typed_by_person
    if typed_by_person(f["loss_run_valuation_date"]):
        assert f["loss_run_valuation_date"]["value"] == "05/01/2025"


def test_empty_missing_and_garbage_never_raise():
    assert not latest_loss_run_valuation({}, [])
    assert not latest_loss_run_valuation({}, [_doc(None), _doc("not a date")])
    assert not latest_loss_run_valuation(None, [_doc("10/20/2026")])
    f = {}
    assert latest_loss_run_valuation(f, [_doc("10/20/2026")])
    assert f["loss_run_valuation_date"]["value"] == "10/20/2026"
