"""26 Oct 2026 (live 6c420291): a loss-run ownership "Yes" lifted every loss run in
the package - including runs excluded when it was given and runs added later. It now
covers the runs on file when it was given; a later run is asked about again."""
from services.loss_history_state import (LOSS_RUN_OWNERSHIP_FIELD, OWNERSHIP_DOCS_KEY,
                                         ownership_answer_covers, ownership_question_open, ownership_scope)
from services.loss_run_identity import match_loss_run_identity


def _run(doc_id, name="CHOICE ELECTRIC LLC", excluded=False):
    return {"doc_id": doc_id, "filename": f"{doc_id}.csv", "doc_type": "loss_run", "excluded": excluded,
            "facts": {"applicant_name": name}}


DEC = {"doc_id": "dec", "filename": "dec.pdf", "doc_type": "dec_page", "facts": {"applicant_name": "CHOICE ELECTRIC LLC"}}


def test_scope_is_the_active_loss_runs_only():
    assert ownership_scope([_run("a"), _run("b", excluded=True), DEC]) == ["a"]


def test_a_yes_lifts_only_the_runs_it_was_given_for():
    docs = [DEC, _run("a"), _run("b")]
    facts = {"applicant_name": "CHOICE ELECTRIC LLC",
             LOSS_RUN_OWNERSHIP_FIELD: {"value": "Yes", "source": "producer", OWNERSHIP_DOCS_KEY: ["a"]}}
    tiers = {d["filename"]: d["tier"] for d in match_loss_run_identity(docs, "CHOICE ELECTRIC LLC", facts)["per_document"]}
    assert tiers == {"a.csv": "strong", "b.csv": "possible"}
    assert ownership_question_open(facts, docs)          # b is still to confirm
    assert not ownership_question_open(facts, [DEC, _run("a")])


def test_an_answer_saved_before_today_keeps_its_package_wide_reach():
    facts = {LOSS_RUN_OWNERSHIP_FIELD: {"value": "Yes", "source": "producer"}}
    assert ownership_answer_covers(facts, _run("anything"))
    assert not ownership_question_open(facts, [_run("x")])
