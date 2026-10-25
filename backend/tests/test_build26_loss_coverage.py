"""Loss-run coverage shown on the review page (24 Oct 2026): display only,
`covered` is the scorer's own count."""
import copy

from services.loss_history_state import combine_loss_run_periods, loss_run_coverage
from services.sqs_service import _resolve_loss_history_years


def _doc(doc_id, start, end, excluded=False):
    return {"doc_id": doc_id, "filename": f"{doc_id}.pdf", "doc_type": "loss_run",
            "excluded": excluded,
            "facts": {"loss_run_period_start": start, "loss_run_period_end": end}}


OLD = _doc("old", "07/15/2021", "07/15/2025")
CUR = _doc("cur", "07/15/2025", "07/15/2026")
FACTS = {"loss_run_period_start": "07/15/2025", "loss_run_period_end": "07/15/2026",
         "years_in_business": "12"}


def test_two_runs_cover_five_of_five():
    cov = loss_run_coverage([OLD, CUR], copy.deepcopy(FACTS))
    assert cov["required"] == 5 and cov["covered"] == 5
    assert cov["years"] == [2021, 2022, 2023, 2024, 2025]
    assert cov["label"] == "5 of 5 years (2021-2025)"
    by_id = {d["doc_id"]: d for d in cov["documents"]}
    assert by_id["old"]["years_label"] == "2021-2024 - 4 years"
    assert by_id["cur"]["years_label"] == "2025 - 1 year"


def test_current_run_only_is_one_of_five():
    cov = loss_run_coverage([CUR], copy.deepcopy(FACTS))
    assert cov["covered"] == 1 and cov["label"] == "1 of 5 years (2025)"


def test_excluded_run_is_listed_and_not_counted():
    cov = loss_run_coverage([dict(OLD, excluded=True), CUR], copy.deepcopy(FACTS))
    assert cov["covered"] == 1
    ex = [d for d in cov["documents"] if d["doc_id"] == "old"][0]
    assert ex["excluded"] is True and ex["years"] == [2021, 2022, 2023, 2024]


def test_no_loss_runs_is_none():
    assert loss_run_coverage([{"doc_type": "dec_page"}], FACTS) is None


def test_covered_equals_the_scorer():
    for docs in ([OLD, CUR], [CUR], [dict(OLD, excluded=True), CUR], [OLD]):
        f = copy.deepcopy(FACTS)
        cov = loss_run_coverage(docs, f)
        combine_loss_run_periods(f, docs)
        assert cov["covered"] == _resolve_loss_history_years(f)
