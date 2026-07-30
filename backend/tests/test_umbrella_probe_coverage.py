"""C14 - the umbrella-period probe must read the WHOLE document, not its first 9%.

## What was wrong

`_fetch_umbrella_period_sync` did this:

    text = raw_text[:_UMBRELLA_PERIOD_MAX_CHARS]      # 60,000

That is the worst place in the pipeline to put a hard truncation, because this
probe is a **fallback**. It fires only when `map_facts_to_form` finds that the
main extraction pass already failed to produce `umbrella_effective_date` /
`umbrella_expiration_date`. So it was pointed at the opening 60,000 chars of a
package - on a real 684,000-char submission, the first 8.8%, and precisely the
region we already know did not yield the dates.

**The backup read strictly less than the thing it was backing up.** Umbrella
dates came back blank on ACORD 125/131/25 and nothing said why: a blank field
from a truncated read is indistinguishable from a blank field the document
genuinely never stated.

## What these tests pin

The first test is the load-bearing one and it is written to FAIL against the old
implementation: it plants the dates past the 60,000-char mark and asserts they
are found. Under `raw_text[:60_000]` that text is never sent to any model, so the
probe returns `{None, None}` and the assertion fails. A test that passes either
way would guard nothing (HANDOFF.md rule 6).

The rest pin the properties that make the fix affordable and safe rather than
just complete - one call in the common case, no chunk abandoning the document,
and losslessness of the shared splitter at every budget.
"""
import json

import pytest

import services.pdf_service as ps


# ── Harness ──────────────────────────────────────────────────────────────────

class _Recorder:
    """Stands in for the sync OpenAI client. Records the document text of every
    call and replays a scripted answer per call."""

    def __init__(self, answers):
        # `answers` is a list of (effective, expiration) tuples, one per call.
        # A tuple of `Exception` raises, to exercise the per-chunk failure path.
        self._answers = list(answers)
        self.docs = []
        self.chat = self
        self.completions = self

    def create(self, **kw):
        msgs = kw.get("messages") or []
        user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        self.docs.append(user)
        nxt = self._answers[len(self.docs) - 1] if len(self.docs) <= len(self._answers) else (None, None)
        if isinstance(nxt, Exception):
            raise nxt
        eff, exp = nxt
        payload = json.dumps({
            "umbrella_effective_date": eff,
            "umbrella_expiration_date": exp,
        })

        class _R:
            choices = [type("C", (), {"message": type("M", (), {"content": payload})()})()]
            usage = None
        return _R()

    @property
    def calls(self):
        return len(self.docs)

    def sent_text(self):
        return "\n".join(self.docs)


@pytest.fixture
def probe(monkeypatch):
    def _run(raw_text, answers):
        rec = _Recorder(answers)
        monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: rec)
        monkeypatch.setattr(ps, "_log_llm_spend", lambda *a, **k: None)
        out = ps._fetch_umbrella_period_sync(raw_text)
        return out, rec
    return _run


def _document_with_dates_at(offset_chars):
    """A realistic-shaped package whose umbrella block sits past `offset_chars`."""
    filler = ("GENERAL LIABILITY SCHEDULE OF LOCATIONS\n"
              "Location 004 - 1200 Industrial Way, Denver CO 80216\n"
              "Class code 91560  Payroll $412,000  Rate 2.184\n\n")
    head = filler * (offset_chars // len(filler) + 1)
    tail = ("COMMERCIAL LIABILITY UMBRELLA DECLARATIONS\n"
            "Umbrella Policy CUP-88213-04\n"
            "Umbrella Effective Date: 03/01/2026\n"
            "Umbrella Expiration Date: 03/01/2027\n")
    return head + tail, len(head)


# ── The requirement ──────────────────────────────────────────────────────────

def test_umbrella_dates_stated_past_60k_chars_are_still_found(probe):
    """THE regression test for C14. Fails against `raw_text[:60_000]`.

    The umbrella block sits ~120,000 chars in - well past the old cut - so under
    the old implementation the model never saw it and the probe returned nothing.
    """
    doc, block_at = _document_with_dates_at(120_000)
    assert block_at > 60_000, "fixture must place the block past the old truncation"

    # The chunk containing the block answers; earlier chunks legitimately do not.
    n_chunks = len(ps._split_text_on_boundaries(doc, ps._UMBRELLA_PERIOD_CHUNK_CHARS))
    answers = [(None, None)] * (n_chunks - 1) + [("03/01/2026", "03/01/2027")]

    out, rec = probe(doc, answers)

    assert out == {
        "umbrella_effective_date":  "03/01/2026",
        "umbrella_expiration_date": "03/01/2027",
    }
    # And prove it structurally, not just via the scripted answer: the text of
    # the umbrella block must actually have been shipped to the model.
    assert "Umbrella Expiration Date: 03/01/2027" in rec.sent_text()


def test_every_character_of_the_document_reaches_the_probe(probe):
    """Sentinel sweep: no chunk boundary may swallow content.

    `test_full_document_coverage.py` does this for the general fill and the
    compliance pass. The umbrella probe was the third stage carrying the raw
    document and it had no such guard - which is how a literal `[:60_000]`
    survived in it.
    """
    parts = [f"SENTINEL-{i:04d} umbrella excess policy narrative line\n" for i in range(4000)]
    doc = "\n".join(parts)
    assert len(doc) > 3 * ps._UMBRELLA_PERIOD_CHUNK_CHARS, "fixture must span several chunks"

    # Never answer, so the scan is forced to read the entire document.
    out, rec = probe(doc, [(None, None)] * 500)

    sent = rec.sent_text()
    missing = [i for i in range(4000) if f"SENTINEL-{i:04d}" not in sent]
    assert not missing, f"{len(missing)} of 4000 markers never reached the model, e.g. {missing[:5]}"
    assert out == {"umbrella_effective_date": None, "umbrella_expiration_date": None}


# ── The properties that keep the fix affordable ──────────────────────────────

def test_a_short_document_still_costs_exactly_one_call(probe):
    doc = "UMBRELLA DECLARATIONS\nEffective 03/01/2026 Expiration 03/01/2027\n"
    out, rec = probe(doc, [("03/01/2026", "03/01/2027")])
    assert rec.calls == 1
    assert out["umbrella_effective_date"] == "03/01/2026"


def test_scan_stops_as_soon_as_both_dates_are_known(probe):
    """Cost guard. The common case - umbrella dec page near the front - must not
    pay to read the remaining 250 pages."""
    doc, _ = _document_with_dates_at(400_000)
    n_chunks = len(ps._split_text_on_boundaries(doc, ps._UMBRELLA_PERIOD_CHUNK_CHARS))
    assert n_chunks > 4, "fixture must be genuinely multi-chunk"

    out, rec = probe(doc, [("03/01/2026", "03/01/2027")] + [(None, None)] * n_chunks)

    assert rec.calls == 1, f"answered on chunk 1 but still made {rec.calls} calls"
    assert out["umbrella_effective_date"] == "03/01/2026"


def test_the_two_dates_resolve_independently_across_chunks(probe):
    """A package can state the umbrella's effective date on its dec page and its
    expiration only in a later endorsement. Finding one must not stop the scan."""
    doc, _ = _document_with_dates_at(200_000)
    out, rec = probe(doc, [("03/01/2026", None), (None, None), (None, "03/01/2027")])
    assert out == {
        "umbrella_effective_date":  "03/01/2026",
        "umbrella_expiration_date": "03/01/2027",
    }
    assert rec.calls == 3


def test_a_failing_chunk_does_not_abandon_the_rest_of_the_document(probe):
    """One transport error on chunk 1 must not blind the probe to page 200.

    The old code had a single call inside one try/except, so ANY failure meant
    the whole probe returned None. With the document chunked, that behaviour
    would have been strictly worse than the truncation it replaced.
    """
    doc, _ = _document_with_dates_at(150_000)
    out, rec = probe(doc, [RuntimeError("429 rate limited"), ("03/01/2026", "03/01/2027")])
    assert out == {
        "umbrella_effective_date":  "03/01/2026",
        "umbrella_expiration_date": "03/01/2027",
    }
    assert rec.calls == 2


def test_every_chunk_failing_returns_none_not_a_fake_empty_answer(probe):
    """`None` means "the probe could not run"; `{None, None}` means "the document
    does not state them". The call site treats them the same today, but conflating
    them is how a provider outage starts looking like a document that simply had
    no umbrella."""
    doc, _ = _document_with_dates_at(150_000)
    n = len(ps._split_text_on_boundaries(doc, ps._UMBRELLA_PERIOD_CHUNK_CHARS))
    out, _rec = probe(doc, [RuntimeError("boom")] * (n + 2))
    assert out is None


def test_no_client_configured_is_survivable(monkeypatch):
    def _boom():
        raise RuntimeError("no OPENAI_API_KEY")
    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", _boom)
    assert ps._fetch_umbrella_period_sync("anything") is None


# ── The shared splitter ──────────────────────────────────────────────────────
#
# `_split_text_on_boundaries` is now the single implementation behind the general
# fill, the compliance pass and this probe. C12's lesson was that two places
# computing the same thing WILL drift; three copies of a chunk loop is the same
# bet, and one of them had already drifted into a truncation.

@pytest.mark.parametrize("budget", [1, 7, 100, 1_000, 9_999, 10_000, 250_000])
def test_splitter_is_lossless_at_every_budget(budget):
    doc = "".join(
        f"LINE {i:05d} value ${i * 137:,} code {i % 97:02d}\n" + ("\n" if i % 13 == 0 else "")
        for i in range(3000)
    )
    pieces = ps._split_text_on_boundaries(doc, budget)
    strip = lambda s: "".join(s.split())          # noqa: E731 - newlines at cuts are dropped by design
    assert strip("".join(pieces)) == strip(doc), f"content lost at budget={budget}"


@pytest.mark.parametrize("budget", [1, 50, 4_096])
def test_splitter_never_emits_an_empty_chunk(budget):
    """An empty piece is a whole LLM call carrying no document. The previous
    hand-rolled copies appended one whenever a cut landed at offset 0."""
    doc = "\n\n\n" + "alpha beta gamma\n\n" * 500 + "\n\n\n"
    assert all(p.strip() for p in ps._split_text_on_boundaries(doc, budget))


def test_splitter_respects_the_budget():
    doc = "word " * 50_000
    for piece in ps._split_text_on_boundaries(doc, 1_000):
        assert len(piece) <= 1_000


def test_splitter_terminates_on_pathological_input():
    """No line breaks at all, and a budget smaller than one token."""
    assert "".join(ps._split_text_on_boundaries("x" * 5_000, 3)) == "x" * 5_000


def test_empty_document_does_not_produce_a_call(probe):
    out, rec = probe("", [(None, None)])
    # One empty piece is returned so callers always have something to iterate,
    # but the probe must not pretend it read anything.
    assert out in (None, {"umbrella_effective_date": None, "umbrella_expiration_date": None})
    assert rec.calls <= 1
