"""Reopening a dismissed or producer-answered SQS recommendation.

Covers the primitive that made it possible (fact retraction, which silently did
nothing before), the flag retraction that rides along with it, and the ordering /
guard rules in the reopen route that keep the download gate honest.

Pure unit tests: the DB is faked, so these run without Postgres like the rest of
the suite.
"""
import asyncio
import inspect
import json
from unittest.mock import patch

import repositories.session_repository as sr
import routes.audit_routes as ar
import services.arq_service as arq
import services.audit_service as aud


# ── Fake asyncpg plumbing ────────────────────────────────────────────────────

class _FakeTx:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


class _FakeConn:
    """Just enough of an asyncpg connection for upd_processing_session."""

    def __init__(self, stored: dict):
        self.stored  = stored
        self.written = None

    def transaction(self):
        return _FakeTx()

    async def fetchrow(self, query, *args):
        # upd_processing_session reads {data, version} FOR UPDATE.
        return {"data": json.dumps(self.stored), "version": 1}

    async def execute(self, query, *args):
        # args[0] is the `clean` payload handed to the UPDATE.
        self.written = args[0]


class _FakeAcquire:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self): return self.conn
    async def __aexit__(self, *a): return False


class _FakePool:
    def __init__(self, conn): self.conn = conn
    def acquire(self): return _FakeAcquire(self.conn)


def _run_upd(stored: dict, updates: dict, delete_facts=None) -> dict:
    """Drive the REAL upd_processing_session against a faked pool and return the
    session dict it would have persisted (facts decrypted again)."""
    conn = _FakeConn(stored)
    with patch.object(sr, "get_pool", lambda: _FakePool(conn)), \
         patch.object(sr, "_save_pdf_bytes", _noop_async):
        asyncio.run(sr.upd_processing_session("sid-1", updates, delete_facts=delete_facts))
    assert conn.written is not None, "no UPDATE was issued"
    return sr._decrypt_facts(dict(conn.written))


async def _noop_async(*a, **k):
    return None


# ── 1. The primitive: fact deletion must actually persist ────────────────────

def test_delete_facts_removes_the_key():
    """The bug this whole feature sat on: the facts merge is additive, so a key
    absent from the update survived. delete_facts must genuinely remove it."""
    stored = {"facts": {"gl_each_occurrence": {"value": "1000000", "source": "producer"},
                        "applicant_name": {"value": "Acme", "source": "ai"}}}
    out = _run_upd(stored, {}, delete_facts=["gl_each_occurrence"])
    assert "gl_each_occurrence" not in out["facts"]
    # Never a blunt instrument - only the named key goes.
    assert out["facts"]["applicant_name"]["value"] == "Acme"


def test_delete_facts_wins_over_a_concurrent_merge_of_the_same_key():
    """delete_facts is applied AFTER the merge, so passing the same key in both
    places retracts it rather than resurrecting it."""
    stored = {"facts": {"gl_each_occurrence": {"value": "1000000", "source": "producer"}}}
    out = _run_upd(
        stored,
        {"facts": {"gl_each_occurrence": {"value": "1000000", "source": "producer"}}},
        delete_facts=["gl_each_occurrence"],
    )
    assert "gl_each_occurrence" not in out["facts"]


def test_deleting_an_absent_key_is_a_noop():
    stored = {"facts": {"applicant_name": {"value": "Acme", "source": "ai"}}}
    out = _run_upd(stored, {}, delete_facts=["never_set", "also_missing"])
    assert out["facts"]["applicant_name"]["value"] == "Acme"


def test_the_sentinel_never_leaks_into_session_data():
    """delete_facts is a keyword arg precisely so it cannot land in the JSONB blob
    the way a magic `updates` key could."""
    stored = {"facts": {"a": {"value": "1"}}}
    out = _run_upd(stored, {}, delete_facts=["a"])
    assert "delete_facts" not in out
    assert "_facts_delete" not in out


# ── 2. The 30-call-site regression guard ─────────────────────────────────────

def test_default_none_preserves_the_additive_merge():
    """Every existing caller passes no delete_facts. Their behaviour - additive
    merge, blank/None values skipped so an in-flight writer can't erase a value -
    must be untouched."""
    stored = {"facts": {"keep": {"value": "x"}, "also_keep": {"value": "y"}}}
    out = _run_upd(stored, {"facts": {"new_key": {"value": "z"},
                                      "keep": None,          # skipped
                                      "also_keep": ""}})     # skipped
    assert out["facts"]["keep"]["value"] == "x"
    assert out["facts"]["also_keep"]["value"] == "y"
    assert out["facts"]["new_key"]["value"] == "z"


def test_delete_facts_is_an_optional_keyword_argument():
    sig = inspect.signature(sr.upd_processing_session)
    p = sig.parameters["delete_facts"]
    assert p.default is None, "existing callers must be unaffected"


# ── 3. clear_producer_answer_from_session uses it, and retracts derived flags ─

def _clear(facts, flags=None, field="gl_each_occurrence"):
    """Run the real clear against a faked session; return (ok, captured_kwargs)."""
    captured = {}

    async def _fake_get(sid, *a, **k):
        return {"facts": dict(facts), "flags": dict(flags or {}), "generated_forms": {}}

    async def _fake_upd(sid, updates, delete_facts=None):
        captured["updates"] = updates
        captured["delete_facts"] = delete_facts

    with patch.object(sr, "get_processing_session", _fake_get), \
         patch.object(sr, "upd_processing_session", _fake_upd):
        ok, _ = asyncio.run(arq.clear_producer_answer_from_session("sid-1", field))
    return ok, captured


def test_clear_passes_delete_facts_not_a_facts_dict():
    """The old code did `del facts[canon]` and passed the dict - which the merge
    then ignored. Passing {"facts": ...} again would re-merge the key straight
    back in, so it must NOT be in updates."""
    ok, cap = _clear({"gl_each_occurrence": {"value": "1000000", "source": "producer"}})
    assert ok is True
    assert cap["delete_facts"] == ["gl_each_occurrence"]
    assert "facts" not in cap["updates"]


def test_clear_only_touches_the_producers_own_answer():
    """A value that came from document extraction is never retracted - reopening
    must not be able to erase real data the client's documents provided."""
    ok, cap = _clear({"gl_each_occurrence": {"value": "1000000", "source": "ai"}})
    assert ok is False
    assert cap == {}


def test_clear_retracts_the_no_loss_flag_it_derived():
    """A conclusion must not outlive the premise. apply_producer_answer_to_session
    sets this flag FROM the answer, so clearing the answer must unset it."""
    ok, cap = _clear(
        {arq.NO_LOSS_INDICATOR_FIELD: {"value": "Yes", "source": "producer"}},
        flags={"no_prior_losses": True},
        field=arq.NO_LOSS_INDICATOR_FIELD,
    )
    assert ok is True
    assert "no_prior_losses" not in cap["updates"]["flags"]


def test_clear_retracts_the_carrier_marketing_flag_it_derived():
    ok, cap = _clear(
        {arq.CARRIER_MARKETING_FIELD: {"value": "Non-renewed", "source": "producer"}},
        flags={"prior_carrier_adverse_action": True},
        field=arq.CARRIER_MARKETING_FIELD,
    )
    assert ok is True
    assert "prior_carrier_adverse_action" not in cap["updates"]["flags"]


def test_clear_leaves_unrelated_flags_alone():
    ok, cap = _clear(
        {"gl_each_occurrence": {"value": "1000000", "source": "producer"}},
        flags={"has_umbrella": True},
    )
    assert ok is True
    # No flag was derived from this fact, so flags are not rewritten at all.
    assert "flags" not in cap["updates"]


# ── 4. The "Reviewed" predicate ──────────────────────────────────────────────

def test_reviewed_predicate_excludes_client_auto_resolved_recs():
    """`action='resolved'` alone is not enough. Recs the client's questionnaire
    auto-resolved carry no producer_answer - the producer never touched them and
    has nothing to reopen, so they must not appear in Reviewed."""
    src = inspect.getsource(aud.get_reviewed_recommendations)
    assert "action = 'dismissed'" in src
    assert "producer_answer IS NOT NULL" in src
    assert "action = 'resolved' AND producer_answer IS NOT NULL" in src


def test_dismissed_export_query_stays_dismissals_only():
    """get_dismissed_recommendations backs the E&O audit-trail export. Widening it
    to answered recs would silently change what that compliance record reports."""
    src = inspect.getsource(aud.get_dismissed_recommendations)
    assert "action='dismissed'" in src
    assert "producer_answer" not in src


def test_answer_recorder_never_writes_action():
    """Stamping action='resolved' here would hide answers that did NOT close the
    gap from the pre-download gate. Only the recalculation's auto-resolve pass,
    which can see whether the rec actually went away, may set it."""
    src = inspect.getsource(aud.mark_recommendation_answer_recorded)
    src = src.replace(aud.mark_recommendation_answer_recorded.__doc__ or "", "")

    # The INSERT column list must not carry action / action_at at all.
    insert_cols = src.split("INSERT INTO sqs_recommendation_audit (")[1].split(")")[0]
    assert "producer_answer" in insert_cols
    assert "action" not in insert_cols

    # The DO UPDATE SET clause must not assign action either. `action` may appear
    # only afterwards, in the WHERE latch that protects an already-actioned row.
    set_clause = src.split("DO UPDATE")[1].split("WHERE")[0]
    assert "producer_answer = EXCLUDED.producer_answer" in set_clause
    assert "action" not in set_clause
    assert "'resolved'" not in set_clause


def test_reopen_preserves_the_submitted_values():
    """Sticky by design: override_reason is the producer's E&O justification and
    producer_answer prefills the reopened card. Only the action-state columns are
    nulled; a new submit is what overwrites them."""
    src = inspect.getsource(aud.reopen_recommendation)
    assert "action=NULL" in src
    assert "action_at=NULL" in src
    assert "sqs_score_at_action=NULL" in src
    assert "override_reason=NULL" not in src
    assert "producer_answer=NULL" not in src


# ── 5. The credit gate is one shared predicate ───────────────────────────────

def test_dismiss_credit_gate():
    # A plain dismiss (sentinel reason) earns nothing - the gap stays on record.
    assert ar._dismiss_earned_credit("No reason provided", 8) is False
    assert ar._dismiss_earned_credit(None, 8) is False
    assert ar._dismiss_earned_credit("", 8) is False
    # A real typed reason with a positive impact earns the credit.
    assert ar._dismiss_earned_credit("Monoline - not applicable", 8) is True
    # No impact, no credit.
    assert ar._dismiss_earned_credit("Monoline", 0) is False
    assert ar._dismiss_earned_credit("Monoline", None) is False


def test_dismiss_route_and_reopen_share_the_gate():
    """If the apply-side and reverse-side predicates ever drifted, scores would
    silently mis-restore on reopen."""
    assert "_dismiss_earned_credit" in inspect.getsource(ar.dismiss_recommendation)
    assert "_dismiss_earned_credit" in inspect.getsource(ar._reapply_dismiss_credits)


# ── 6. Reopen route: ordering and the phantom-row guard ──────────────────────

class _Recorder:
    def __init__(self): self.calls = []


def _run_reopen(row, active_rec_ids, rec_id="rec_gl_each_occurrence"):
    """Drive the real route with every collaborator faked; return (response, order)."""
    rec = _Recorder()

    async def _owner(sid, user): return None
    async def _get_row(sid, rid): return row
    async def _clear(sid, field):
        rec.calls.append("clear"); return True, ["ACORD_125"]
    async def _recalc(sid):
        rec.calls.append("recalculate"); return {}
    async def _replay(sid, exclude_rec_id=None):
        rec.calls.append("replay_credits")
    async def _payload(sid):
        rec.calls.append("read_back")
        return ({"ACORD_125": {
            "new_sqs_score": 71, "new_grade": "C", "new_tier": "Needs Work",
            "new_tier_color": "orange",
            "recommendations": [{"rec_id": r} for r in active_rec_ids],
        }}, 68, "Not Ready")
    async def _null_row(sid, rid):
        rec.calls.append("null_audit_row"); return True

    fake_arq = type("m", (), {
        "clear_producer_answer_from_session": staticmethod(_clear),
        "recalculate_session_scores": staticmethod(_recalc),
    })

    req = type("R", (), {"session_id": "sid-1", "rec_id": rec_id, "form_id": None})()
    with patch.object(ar, "_verify_session_owner", _owner), \
         patch.object(ar, "get_recommendation_audit_row", _get_row), \
         patch.object(ar, "_reapply_dismiss_credits", _replay), \
         patch.object(ar, "_forms_payload_with_recs", _payload), \
         patch.object(ar, "_reopen_recommendation_row", _null_row), \
         patch.dict("sys.modules", {"services.arq_service": fake_arq}):
        resp = asyncio.run(ar.reopen_recommendation(req, {"id": "u1"}))
    return json.loads(resp.body), rec.calls


_ANSWERED = {
    "rec_id": "rec_gl_each_occurrence", "action": "resolved",
    "producer_answer": "1000000", "field": "gl_each_occurrence",
    "override_reason": None, "score_impact": 15, "form_id": "ACORD_125",
}
_DISMISSED_WITH_REASON = {
    "rec_id": "rec_gl_each_occurrence", "action": "dismissed",
    "producer_answer": None, "field": "gl_each_occurrence",
    "override_reason": "Monoline - not applicable", "score_impact": 8,
    "form_id": "ACORD_125",
}
_DISMISSED_NO_REASON = {
    "rec_id": "rec_gl_each_occurrence", "action": "dismissed",
    "producer_answer": None, "field": "gl_each_occurrence",
    "override_reason": "No reason provided", "score_impact": 8,
    "form_id": "ACORD_125",
}


def test_answered_reopen_clears_the_fact_then_rescores_then_nulls_last():
    """Ordering is load-bearing. recalculate_session_scores' auto-resolve pass only
    sees rows with action IS NULL, so nulling the row BEFORE it would let that pass
    immediately re-stamp 'resolved' and defeat the reopen."""
    body, order = _run_reopen(_ANSWERED, ["rec_gl_each_occurrence"])
    assert body["success"] is True
    assert body["reopened"] is True
    assert body["cleared"] is True
    assert order == ["clear", "recalculate", "replay_credits", "read_back", "null_audit_row"]
    assert order.index("null_audit_row") > order.index("recalculate")


def test_reopen_returns_the_previous_answer_for_prefill():
    body, _ = _run_reopen(_ANSWERED, ["rec_gl_each_occurrence"])
    assert body["previous_answer"] == "1000000"


def test_reopen_does_not_null_the_row_when_the_gap_did_not_come_back():
    """Several recs are satisfied by a COMBINATION of facts (rec_min_cope needs
    four), so retracting one value can leave the rec legitimately closed. Nulling
    `action` anyway creates a row that blocks the download preflight forever while
    rendering nowhere in the panel."""
    body, order = _run_reopen(_ANSWERED, ["some_other_rec"])
    assert body["reopened"] is False
    assert "null_audit_row" not in order
    # The retraction still happened and was rescored - only the row survives.
    assert body["cleared"] is True
    assert "recalculate" in order


def test_dismissed_with_reason_rescores_and_replays_other_credits():
    """The credit was baked destructively into the stored score with no baseline,
    so a rescore is the only honest way to reverse it - and the OTHER dismissals'
    credits must be put back or the score drops by all of them."""
    body, order = _run_reopen(_DISMISSED_WITH_REASON, ["rec_gl_each_occurrence"])
    assert body["reopened"] is True
    assert body["cleared"] is False          # a dismissal never wrote a fact
    assert "clear" not in order
    assert order == ["recalculate", "replay_credits", "read_back", "null_audit_row"]


def test_dismissed_without_reason_skips_the_rescore_entirely():
    """No reason means no credit was ever applied and no fact was ever written.
    Rescoring anyway would wipe every OTHER outstanding dismiss credit for nothing."""
    body, order = _run_reopen(_DISMISSED_NO_REASON, ["rec_gl_each_occurrence"])
    assert body["reopened"] is True
    assert "recalculate" not in order
    assert "replay_credits" not in order
    assert order == ["read_back", "null_audit_row"]


def test_reopen_404s_on_an_unknown_rec():
    import pytest
    from fastapi import HTTPException

    async def _owner(sid, user): return None
    async def _none(sid, rid): return None

    req = type("R", (), {"session_id": "sid-1", "rec_id": "nope", "form_id": None})()
    with patch.object(ar, "_verify_session_owner", _owner), \
         patch.object(ar, "get_recommendation_audit_row", _none):
        with pytest.raises(HTTPException) as ei:
            asyncio.run(ar.reopen_recommendation(req, {"id": "u1"}))
    assert ei.value.status_code == 404
