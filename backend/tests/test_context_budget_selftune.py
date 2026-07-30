"""The call budget must survive being set too high (C20).

`GPT_CALL_BUDGET_CHARS` is a guess about the model's usable input window, and
the guess matters a lot: on a 671k-char / 271-page submission a 380k budget
produced **172** LLM calls where a 760k budget produces **63**, because every
extra document chunk multiplies the call count by the number of field
sub-batches. So the value wants to be raised - but if it is raised past what the
model accepts, every call returns a context-length 400, all three retries burn,
`_chat_json` returns {} and whole batches ship BLANK with nothing on screen to
say so.

These tests lock in the safety net: the first overflow halves the budget
process-wide and the affected batch is re-split and retried, so a bad guess
costs one wasted call instead of a form full of holes.
"""
import json
import os
import threading

import pytest

import services.pdf_service as ps


class _CtxError(Exception):
    """Shaped like an OpenAI 400 for context length."""
    status_code = 400

    def __init__(self):
        super().__init__(
            "This model's maximum context length is 128000 tokens, however you "
            "requested 190123 tokens. Please reduce the length of the messages."
        )


@pytest.fixture(autouse=True)
def _restore_budget():
    original = ps._effective_budget_chars
    yield
    ps._effective_budget_chars = original


def test_context_length_error_is_recognised():
    assert ps._is_context_length_error(_CtxError()) is True


def test_ordinary_failures_are_not_mistaken_for_overflow():
    """Only a real context rejection may shrink the budget - a 429 or a plain
    400 must keep the normal retry path."""
    class _E(Exception):
        def __init__(self, msg, code):
            super().__init__(msg)
            self.status_code = code

    assert ps._is_context_length_error(_E("Rate limit reached", 429)) is False
    assert ps._is_context_length_error(_E("Gateway timeout", 504)) is False
    assert ps._is_context_length_error(
        _E("Invalid value for 'response_format'", 400)) is False


def test_budget_halves_and_floors():
    ps._effective_budget_chars = 760_000
    assert ps._shrink_budget_after_overflow(_CtxError()) == 380_000
    assert ps._shrink_budget_after_overflow(_CtxError()) == 190_000
    for _ in range(20):
        ps._shrink_budget_after_overflow(_CtxError())
    assert ps._effective_budget_chars == 40_000, "must floor, never reach zero"


def test_shrink_is_thread_safe():
    """Sub-batches run concurrently, so several threads can overflow at once."""
    ps._effective_budget_chars = 640_000
    barrier = threading.Barrier(8)

    def _hit():
        barrier.wait()
        ps._shrink_budget_after_overflow(_CtxError())

    ts = [threading.Thread(target=_hit) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # Each call halves once; the result must be a clean power-of-two division,
    # never a torn value.
    assert ps._effective_budget_chars in (
        640_000 // (2 ** n) for n in range(1, 9)
    ), f"torn budget value {ps._effective_budget_chars}"


class _OverflowThenSucceed:
    """Rejects any prompt above `limit` chars, like the real API would."""

    def __init__(self, limit):
        self.limit = limit
        self.rejected = 0
        self.accepted = 0
        self._lock = threading.Lock()
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        user = next(m["content"] for m in kwargs["messages"] if m["role"] == "user")
        system = next(m["content"] for m in kwargs["messages"] if m["role"] == "system")
        with self._lock:
            if len(user) + len(system) > self.limit:
                self.rejected += 1
                raise _CtxError()
            self.accepted += 1

        class _R:
            choices = [type("C", (), {"message": type(
                "M", (), {"content": '{"values": {}, "raw_text_sourced": [], '
                                     '"question_grounding": {}}'})()})()]
            usage = None
        return _R()


def test_an_over_large_budget_recovers_instead_of_blanking_the_batch(monkeypatch):
    """The whole point: guess high, and the run still completes."""
    monkeypatch.setattr(ps, "_GPT_CALL_BUDGET_CHARS", 400_000)
    ps._effective_budget_chars = 400_000
    client = _OverflowThenSucceed(limit=120_000)
    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: client)

    path = os.path.join(ps.FORMS_SCHEMAS_DIR, "ACORD_25_schema.json")
    with open(path, encoding="utf-8") as fh:
        schema = json.load(fh)
    facts = {"applicant_name": "Ridgeline Roofing"}
    _mapped, unmatched, _ = ps.compute_form_gaps("ACORD_25", schema, facts)
    unmatched = dict(list(unmatched.items())[:40])

    raw = ("DECLARATIONS PAGE - Ridgeline Roofing & Sheet Metal LLC\n"
           "Policy CPP-4471902-03  Carrier Meridian Mutual Casualty\n") * 4000

    ps._fill_unmatched_with_gpt(unmatched, facts, "ACORD_25", raw_text=raw)

    assert client.rejected >= 1, "fixture did not exercise the overflow path"
    assert client.accepted >= 1, (
        "after the budget shrank, the batch was never successfully re-sent - "
        "those fields would ship BLANK, which is the failure this guards against"
    )
    assert ps._effective_budget_chars < 400_000, "budget did not shrink"
