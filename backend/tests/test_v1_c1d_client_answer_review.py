"""V1 plan C1-D - the producer's post-generation decision list (2026-08-21).

C1-C routed held client answers into the Data Consistency picker. That was
WRONG and this file pins why: confirming there re-runs `_finalize_pipeline`,
which sets `generated_forms: {}` - it wipes the producer's forms. The client
answers AFTER generation, so the held answer needs a post-generation door.

Also covers Q7: human-provenance facts surviving a pipeline re-run.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import inspect                                                    # noqa: E402
import pytest                                                     # noqa: E402

from services import client_answer_review as car                  # noqa: E402
from services import fact_state as fs                             # noqa: E402


HELD = {
    "num_employees": {"client_value": "25", "source_value": "18",
                      "field_name": "num_employees", "held_at": "2026-08-21T00:00:00Z"},
}


# ═════════════════════════════════════════════════════════════════════════════
# The rows the producer sees
# ═════════════════════════════════════════════════════════════════════════════

class TestReviewRows:
    def test_nothing_held_means_no_section(self):
        assert car.build_review_rows({}) == []
        assert car.build_review_rows(None) == []
        assert car.build_review_rows({"client_answer_conflicts": {}}) == []

    def test_a_held_answer_becomes_one_row_with_both_values(self):
        rows = car.build_review_rows({"client_answer_conflicts": HELD})
        assert len(rows) == 1
        row = rows[0]
        assert row["fact_key"] == "num_employees"
        assert row["client_value"] == "25"
        assert row["source_value"] == "18"
        assert row["label"] == "Employee Count"      # from RECONCILABLE_FIELDS
        assert "does not match" in row["reason"]

    def test_it_falls_back_to_the_facts_copy_for_older_sessions(self):
        rows = car.build_review_rows({"facts": {"_client_answer_conflicts": HELD}})
        assert len(rows) == 1

    def test_an_entry_with_no_client_value_is_ignored(self):
        assert car.build_review_rows(
            {"client_answer_conflicts": {"num_employees": {"client_value": "  "}}}) == []

    def test_an_unlabelled_fact_still_gets_a_readable_label(self):
        rows = car.build_review_rows({"client_answer_conflicts": {
            "some_new_fact": {"client_value": "a", "source_value": "b"}}})
        assert rows[0]["label"] == "Some New Fact"

    def test_rows_are_stable_order(self):
        rows = car.build_review_rows({"client_answer_conflicts": {
            "zzz_fact": {"client_value": "1", "source_value": "2"},
            "aaa_fact": {"client_value": "3", "source_value": "4"}}})
        assert [r["fact_key"] for r in rows] == ["aaa_fact", "zzz_fact"]


# ═════════════════════════════════════════════════════════════════════════════
# THE REASON THIS MODULE EXISTS - the picker door wipes the forms
# ═════════════════════════════════════════════════════════════════════════════

class TestItDoesNotUseThePickerDoor:
    def test_the_picker_path_really_does_wipe_generated_forms(self):
        """If this ever stops being true, revisit C1-D - but do not assume it."""
        from services import extraction_pipeline as ep
        src = inspect.getsource(ep._finalize_pipeline)
        assert '"generated_forms":      {}' in src or '"generated_forms": {}' in src

    def test_resolution_uses_the_post_generation_stamper(self):
        src = inspect.getsource(car.resolve_client_answer)
        assert "apply_producer_answer_to_session" in src
        assert "confirm_underwriting_value" not in src
        assert "_finalize_pipeline" not in src

    def test_an_unknown_choice_is_rejected_before_anything_is_touched(self):
        import asyncio
        out = asyncio.run(car.resolve_client_answer("s", "num_employees", "whatever"))
        assert out["ok"] is False


# ═════════════════════════════════════════════════════════════════════════════
# Q7 - human answers survive a pipeline re-run
# ═════════════════════════════════════════════════════════════════════════════

class TestHumanFactsSurviveARerun:
    def test_human_provenance_facts_finds_every_actor(self):
        facts = {
            "a": {"value": "1", "source": "client_arq", "confidence": "client_arq"},
            "b": {"value": "2", "source": "producer", "confidence": "filled"},
            "c": {"value": "3", "source": "user_confirmed"},
            "d": {"value": "4", "confidence": "ai_high", "source": "ai"},
            "e": {"value": "5", "confidence": "deterministic"},
            "_private": {"value": "6", "source": "producer"},
            "bare": "scalar",
        }
        got = fs.human_provenance_facts(facts)
        assert set(got) == {"a", "b", "c"}

    def test_an_empty_human_value_is_not_carried(self):
        assert fs.human_provenance_facts({"a": {"value": "", "source": "producer"}}) == {}
        assert fs.human_provenance_facts({"a": {"value": None, "source": "producer"}}) == {}

    def test_none_and_non_dict_are_safe(self):
        assert fs.human_provenance_facts(None) == {}
        assert fs.human_provenance_facts("nope") == {}

    def test_the_pipeline_accepts_and_uses_prior_facts(self):
        from services import extraction_pipeline as ep
        sig = inspect.signature(ep._finalize_pipeline)
        assert "prior_facts" in sig.parameters
        src = inspect.getsource(ep._finalize_pipeline)
        assert "human_provenance_facts" in src

    def test_every_session_bearing_caller_passes_prior_facts(self):
        """A re-run that forgets this silently destroys human answers again."""
        from services import extraction_pipeline as ep
        src = inspect.getsource(ep)
        n_conf = src.count('client_answer_conflicts=session.get("client_answer_conflicts") or {},')
        n_prior = src.count('prior_facts=session.get("facts") or {},')
        assert n_conf >= 4 and n_prior == n_conf, (n_conf, n_prior)

    def test_a_re_run_holds_a_human_value_the_documents_now_contradict(self):
        """Spec-derived, not invented: client rule 1.5 owns this case."""
        from services import extraction_pipeline as ep
        src = inspect.getsource(ep._finalize_pipeline)
        assert "_held_client[_k]" in src
        assert "client_value" in src


# ═════════════════════════════════════════════════════════════════════════════
# B13 - clearing a held answer must actually clear it
# ═════════════════════════════════════════════════════════════════════════════

class TestTheHoldIsReallyReleased:
    """The facts merge in upd_processing_session is ADDITIVE: a key simply
    absent from updates["facts"] is PRESERVED. So `facts.pop(...)` cleared
    nothing in the database and the hold came back on the next read. The
    codebase's own escape hatch is `delete_facts` - use it."""

    def test_the_resolver_retracts_the_key_explicitly(self):
        src = inspect.getsource(car.resolve_client_answer)
        assert "delete_facts=" in src
        assert "FACTS_KEY" in src

    def test_the_arq_apply_retracts_it_too(self):
        from services import arq_service
        src = inspect.getsource(arq_service.apply_arq_answers_to_session)
        assert "delete_facts=" in src

    def test_the_additive_merge_really_is_additive(self):
        """If this ever stops being true, the delete_facts calls above become
        unnecessary rather than wrong - but do not assume, check."""
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "repositories" / "session_repository.py").read_text(encoding="utf-8")
        assert "delete_facts" in src
        assert "additive" in src.lower()


# ═════════════════════════════════════════════════════════════════════════════
# BRENT DECISION Q4 (2026-08-21) - a disagreeing box ships the suggestion
# ═════════════════════════════════════════════════════════════════════════════

class TestQ4PatchTheSuggestedValue:
    def test_no_cross_document_conflict_withholds_a_box_any_more(self):
        from services.underwriting_consistency import CONFLICT_WITHHOLD_KEYS
        assert CONFLICT_WITHHOLD_KEYS == frozenset()

    def test_the_umbrella_conflict_is_still_RAISED_just_not_blanked(self):
        """Brent answered "patch the suggested value" - he did not ask us to
        stop detecting the conflict. Client rule 1.4 still requires it visible
        and routed to the producer."""
        from services.underwriting_consistency import (
            assess_underwriting_consistency, unresolved_withheld_keys)
        docs = [{"filename": "dec.pdf", "doc_type": "policy", "text": "x",
                 "doc_id": "1", "facts": {"umbrella_limit": "$3,000,000"}},
                {"filename": "coi.pdf", "doc_type": "certificate", "text": "x",
                 "doc_id": "2", "facts": {"umbrella_limit": "$1,000,000"}}]
        r = assess_underwriting_consistency(docs, {})
        row = next(f for f in r["fields"] if f["fact_key"] == "umbrella_limit")
        assert row["status"] == "conflict"           # still detected
        assert row["review_required"] is True        # still routed
        assert len(row["values"]) == 2               # both retained
        assert row["conflict_reason"]                # reason recorded
        assert unresolved_withheld_keys(r, {}) == []  # but nothing blanks

    def test_an_INTRA_document_conflict_still_blanks(self):
        """Brent was asked about two DOCUMENTS disagreeing. Principle 7 forbids
        extending a ruling past the question, so the separate intra-document
        limit-conflict path is untouched."""
        from services import extraction_service as es
        src = inspect.getsource(es._flag_intra_document_limit_conflicts)
        assert "_uw_conflicted_keys" in src

    def test_reverting_is_a_one_line_change(self):
        """The decision is reversible by putting the key back - nothing else."""
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "services" / "underwriting_consistency.py").read_text(encoding="utf-8")
        assert "CONFLICT_WITHHOLD_KEYS: frozenset = frozenset()" in src
        assert "BRENT DECISION 2026-08-21" in src


# ═════════════════════════════════════════════════════════════════════════════
# Route + payload wiring
# ═════════════════════════════════════════════════════════════════════════════

class TestWiring:
    def test_the_session_endpoint_serves_the_rows(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "routes" / "form_routes.py").read_text(encoding="utf-8")
        assert '"client_answer_review": _car_rows(proc_session)' in src

    def test_the_resolve_endpoint_exists_and_checks_ownership(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "routes" / "form_routes.py").read_text(encoding="utf-8")
        assert '@router.post("/api/client-answer/resolve")' in src
        block = src.split('@router.post("/api/client-answer/resolve")')[1][:1200]
        assert "Access denied" in block

    def test_the_request_model_exists(self):
        from models.schemas import ClientAnswerResolveRequest
        assert set(ClientAnswerResolveRequest.model_fields) == {
            "session_id", "fact_key", "choice"}

    @pytest.mark.parametrize("needle", [
        "clientAnswerReview",                 # state
        "/api/client-answer/resolve",         # resolver
        "Needs your decision",                # the new section
        "loss_run_match_detail?.notes",       # F4 notes
        'f.status === "scoped"',              # F2b rows
        "f.conflict_reason",                  # F10 reason
    ])
    def test_the_frontend_renders_it(self, needle):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[2]
               / "frontend" / "src" / "components" / "form" / "AcordModal.jsx"
               ).read_text(encoding="utf-8")
        assert needle in src, needle
