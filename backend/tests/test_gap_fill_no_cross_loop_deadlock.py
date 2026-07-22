"""
Regression tests for the form-generation HANG (live, 2026-07-20).

Symptom
-------
Package generation stopped dead partway through the gap-fill pass. The last
log line was a compliance batch dispatch, e.g.

    gpt_fill COMPLIANCE: form=COMBINED_B2of3 questions=36 batches=4

followed by 4 retry lines but only THREE `HTTP 200 OK` responses. The fourth
call never returned, no exception was ever raised, and every pdf_service log
line stopped permanently. The request never completed and the UI spinner ran
forever.

Root cause
----------
`_fill_unmatched_with_gpt` dispatches its LLM calls onto ThreadPoolExecutor
worker threads. Each call used to run `asyncio.run(...)` - creating a BRAND NEW
event loop per call - while sharing the single module-level `AsyncOpenAI`
client (and its one `httpx.AsyncClient` connection pool).

An `httpx.AsyncClient` binds both its pooled connections AND its timeout timers
to the event loop that created them. When a worker picked up a pooled
connection created on another thread's already-closed loop, the await parked on
a dead loop: it could never complete, and the timeout could never fire because
that timer lived on the dead loop too. The worker blocked forever, and
`concurrent.futures.as_completed()` waited on that future forever - hanging the
whole request with no error to log.

Fix
---
The threaded gap-fill path now uses a SYNCHRONOUS OpenAI client
(`_get_openai_form_fill_client_sync`, backed by a thread-safe `httpx.Client`)
plus `llm_limiter.llm_slot_sync()`. No event loop is created per call, so no
client state is ever shared across loops.

These tests pin the structural guarantee, since the real deadlock is a race
that cannot be reliably reproduced in-process.
"""

import json
import os
import sys
import threading
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.pdf_service as pdf_service  # noqa: E402
from utils.llm_limiter import llm_slot_sync  # noqa: E402

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "forms_schemas", "ACORD_140_schema.json")
with open(_SCHEMA_PATH, encoding="utf-8") as _f:
    _ACORD_140_SCHEMA = json.load(_f)

_RAW_TEXT = "Location 1: Building, $3,150,000. Location 2: Building, $2,480,000."


def _unmatched_fields(n: int = 8):
    """A handful of real ACORD 140 fields - enough to drive the gap-fill pass."""
    keys = [
        f"CommercialProperty_Premises_{col}_{row}"
        for col in ("SubjectOfInsuranceCode", "LimitAmount", "CoinsurancePercent", "DeductibleAmount")
        for row in ("A", "B")
    ][:n]
    return {k: _ACORD_140_SCHEMA[k] for k in keys if k in _ACORD_140_SCHEMA}


def _fake_sync_client(captured, calling_threads=None):
    """Stand-in for the SYNC OpenAI client. Records the calling thread so we can
    prove the calls really do run on worker threads (not marshalled onto a loop)."""
    def _create(**kwargs):
        if calling_threads is not None:
            calling_threads.add(threading.current_thread().name)
        captured.append(kwargs.get("messages"))
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = json.dumps({"values": {}, "raw_text_sourced": []})
        return resp

    client = MagicMock()
    client.chat.completions.create = MagicMock(side_effect=_create)
    return client


def test_gap_fill_never_touches_the_async_client():
    """THE regression guard: the gap-fill pass must never obtain the shared
    AsyncOpenAI client. That client is only safe on the single main event loop;
    reaching for it from these worker threads is exactly what deadlocked."""
    captured = []
    async_factory = MagicMock(name="_get_openai_form_fill_client")

    with patch.object(pdf_service, "_get_openai_form_fill_client_sync",
                      return_value=_fake_sync_client(captured)), \
         patch.object(pdf_service, "_get_openai_form_fill_client", async_factory):
        pdf_service._fill_unmatched_with_gpt(
            _unmatched_fields(), facts={}, form_id="ACORD_140", raw_text=_RAW_TEXT,
        )

    assert captured, "gap fill made no LLM calls at all - test is not exercising the path"
    async_factory.assert_not_called()


def test_gap_fill_makes_calls_without_creating_an_event_loop():
    """`asyncio.run()` per call was the mechanism that stranded connections on
    dead loops. The threaded path must now be fully synchronous."""
    captured = []
    with patch.object(pdf_service, "_get_openai_form_fill_client_sync",
                      return_value=_fake_sync_client(captured)), \
         patch.object(pdf_service, "_run_coro_sync",
                      MagicMock(side_effect=AssertionError(
                          "gap fill must not wrap its LLM calls in asyncio.run()"))):
        pdf_service._fill_unmatched_with_gpt(
            _unmatched_fields(), facts={}, form_id="ACORD_140", raw_text=_RAW_TEXT,
        )
    assert captured, "gap fill made no LLM calls at all"


def test_umbrella_period_probe_has_a_sync_entry_point():
    """`map_facts_to_form` runs on a worker thread and previously reached the
    umbrella probe through asyncio.run() on the shared async client - the same
    defect. It must now have a directly-callable sync implementation."""
    assert hasattr(pdf_service, "_fetch_umbrella_period_sync")
    with patch.object(pdf_service, "_get_openai_form_fill_client_sync",
                      return_value=_fake_sync_client([])), \
         patch.object(pdf_service, "_get_openai_form_fill_client",
                      MagicMock(side_effect=AssertionError("must not use async client"))):
        # Returns None here (the fake reply has no umbrella keys); the point is
        # that it completes synchronously without touching the async client.
        pdf_service._fetch_umbrella_period_sync("Umbrella policy period: 08/01/2026 to 08/01/2027")


def test_llm_slot_sync_releases_its_slot():
    """A leaked slot would starve every later call and stall generation just as
    badly as the original deadlock - so acquire/release must balance, including
    when the guarded block raises."""
    from utils import llm_limiter

    before = llm_limiter._thread_sem._value  # type: ignore[attr-defined]
    with llm_slot_sync():
        during = llm_limiter._thread_sem._value  # type: ignore[attr-defined]
        assert during == before - 1, "slot was not actually acquired"
    assert llm_limiter._thread_sem._value == before, "slot leaked on the happy path"  # type: ignore[attr-defined]

    try:
        with llm_slot_sync():
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert llm_limiter._thread_sem._value == before, "slot leaked when the block raised"  # type: ignore[attr-defined]


def test_llm_slot_sync_is_reentrant_across_threads():
    """Concurrent workers must all get through; a permanently-held slot is the
    other way this pass can hang."""
    from utils import llm_limiter

    before = llm_limiter._thread_sem._value  # type: ignore[attr-defined]
    done = []

    def _worker():
        with llm_slot_sync():
            done.append(threading.current_thread().name)

    threads = [threading.Thread(target=_worker, name=f"w{i}") for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not any(t.is_alive() for t in threads), "a worker never acquired a slot (deadlock)"
    assert len(done) == 8
    assert llm_limiter._thread_sem._value == before, "slots leaked under concurrency"  # type: ignore[attr-defined]


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
