"""Open again after a document was added (owner, 24 Oct 2026): a fix that filled a
blank undoes whatever documents came since; a fix that REPLACED a document value
still refuses once the documents changed (its old value may no longer be true)."""
from services import issue_fix_undo as u

ANSWER = {"value": "Yes", "source": "producer", "value_state": "present"}


def _session(docs, facts):
    return {"docs": docs, "facts": facts, "flags": {}, "generated_forms": {}}


def _doc(i):
    return {"doc_id": f"d{i}", "doc_type": "dec_page", "excluded": False}


def test_a_blank_filled_answer_undoes_after_a_new_document():
    before = _session([_doc(1)], {})
    receipt = {"facts": {"x": {"before": {"__absent__": True}, "after": ANSWER}},
               "docs": u.docs_fingerprint(before)}
    now = _session([_doc(1), _doc(2)], {"x": {**ANSWER, "evidence_state": "user_confirmed"}})
    state, plan = u.plan_undo(now, receipt)
    assert state == "ok" and "x" in plan.get("delete_facts", plan.get("delete", ["x"]))


def test_a_replaced_document_value_still_refuses_after_a_new_document():
    before = _session([_doc(1)], {})
    receipt = {"facts": {"x": {"before": {"value": "No", "source": "ai"}, "after": ANSWER}},
               "docs": u.docs_fingerprint(before)}
    now = _session([_doc(1), _doc(2)], {"x": ANSWER})
    assert u.plan_undo(now, receipt) == ("changed", {"changed": ["documents"]})
