"""Extraction chunk sizing must be DERIVED, CLAMPED, and quality-bound.

It used to be one hand-typed literal with no provenance:

    _MODEL_CHUNK_CHARS = {"claude": 28_000, "openai": 100_000}

Three defects, only one of which was the number:

  1. No provenance. Nothing said where 100,000 came from or what would make it
     wrong. Gap fill meanwhile derived its budget from the model spec, so the two
     halves of the pipeline disagreed about the same model - 56,357 chars per call
     for extraction against 899,393 for gap fill.
  2. No capacity guard. Nothing compared it to the model's real window, so an
     over-large value would have failed every call on context length with no
     warning at import.
  3. The carry-over overlap was computed as `raw // 7`, coupling two unrelated
     concerns: changing the chunk size silently changed how much context each
     chunk inherited.

THE POINT OF THESE TESTS is that deriving the value must NOT become an excuse to
raise it. Capacity is ~20x the quality ceiling. That gap is not reclaimable waste
- it is the measured difference between a stage that works (extraction, ~14k
tokens/call, 61 facts and 100% coverage) and one that invents ACORD field names
(gap fill, ~170k tokens/call - improving-ll.md C21/C22).
"""
import random

import pytest

import services.extraction_service as ex


def _fixture(n_sections=1400, seed=7):
    """Dec-page-shaped text with ACORD-style section headers, so the section
    chunker behaves as it does on a real package."""
    rnd = random.Random(seed)
    parts = []
    for i in range(n_sections):
        parts.append(f"COMMERCIAL GENERAL LIABILITY COVERAGE PART {i}:")
        for j in range(rnd.randint(4, 12)):
            parts.append(
                f"  Policy 6E7-40-02 line {i}.{j} each occurrence $1,000,000 "
                f"aggregate $2,000,000 endorsement CG{2000 + j}"
            )
    return "\n".join(parts)


# ── Behaviour must not have changed ──────────────────────────────────────────

def test_derivation_reproduces_the_historical_chunk_count():
    """The refactor changed the effective size 56,357 -> 56,000 chars (0.6%).
    On identical text that must produce the SAME number of chunks, or this was a
    behaviour change dressed up as a cleanup."""
    text = _fixture()
    old = len(ex._chunk_by_sections(text, 56_357, 100))   # the historical value
    new = len(ex._chunk_by_sections(text, ex._effective_chunk_size("openai"), 100))
    assert old == new, (
        f"chunk count moved {old} -> {new}. The derivation was supposed to justify "
        f"the existing behaviour, not alter it. Either restore the effective size "
        f"or land the change deliberately with an accuracy baseline."
    )


def test_effective_size_is_within_a_percent_of_the_historical_value():
    e = ex._effective_chunk_size("openai")
    assert abs(e - 56_357) / 56_357 < 0.01, (
        f"effective chunk size is {e:,}, more than 1% from the historical 56,357. "
        f"If that is intended it needs an accuracy baseline, not a refactor."
    )


# ── The quality ceiling must be the binding one ──────────────────────────────

def test_quality_ceiling_binds_not_capacity():
    """THE load-bearing assertion in this file.

    If capacity ever becomes the smaller number, extraction has been silently
    scaled up toward the C21 cliff - the exact failure mode that costs filled
    fields on the gap-fill side."""
    overhead = ex._compute_prompt_overhead("openai")
    quality = ex._EXTRACTION_DOC_TOKENS_PER_CALL * ex._CHARS_PER_TOKEN
    capacity = ex._context_capacity_chars("openai") - overhead
    assert quality < capacity, (
        f"capacity ({capacity:,}) is now the binding ceiling instead of quality "
        f"({quality:,}). Extraction is being sized by what FITS rather than by what "
        f"the model reads carefully. See improving-ll.md C21."
    )
    assert ex._effective_chunk_size("openai") == quality


def test_extraction_stays_far_below_the_measured_degradation_point():
    """~170k tokens/call is where the model stopped copying ACORD field names.
    ~14k is the known-good point. Extraction must stay near the good end."""
    tok = ex._effective_chunk_size("openai") / ex._CHARS_PER_TOKEN
    assert tok < 60_000, (
        f"extraction now sends {tok:,.0f} document tokens per call. Degradation was "
        f"measured at ~170,000 and the known-good point is ~14,000; anything "
        f"approaching the former needs evidence first."
    )


# ── The capacity guard must exist and work ───────────────────────────────────

def test_an_impossible_override_is_clamped_not_left_to_fail(monkeypatch, caplog):
    """Defect 2. An override that cannot fit the window must clamp loudly, not
    make every call 400 on context length."""
    import logging
    monkeypatch.setattr(ex, "_EXTRACTION_DOC_TOKENS_PER_CALL", 10_000_000)
    with caplog.at_level(logging.WARNING, logger="services.extraction_service"):
        got = ex._effective_chunk_size("openai")
    capacity = ex._context_capacity_chars("openai") - ex._compute_prompt_overhead("openai")
    assert got == capacity, "an impossible value was not clamped to capacity"
    assert any("clamping" in r.message for r in caplog.records), (
        "the clamp happened silently - the misconfiguration must be visible"
    )


def test_capacity_tracks_the_model_window():
    """Change the model, and the ceiling must follow. This is what the hand-typed
    literal could never do."""
    monkey = dict(ex._MODEL_CONTEXT_TOKENS)
    try:
        ex._MODEL_CONTEXT_TOKENS["openai"] = 40_000      # a much smaller model
        small = ex._context_capacity_chars("openai")
        ex._MODEL_CONTEXT_TOKENS["openai"] = 400_000
        big = ex._context_capacity_chars("openai")
        assert small < big
    finally:
        ex._MODEL_CONTEXT_TOKENS.clear()
        ex._MODEL_CONTEXT_TOKENS.update(monkey)


# ── The overlap must be decoupled ────────────────────────────────────────────

def test_overlap_is_independent_of_chunk_size(monkeypatch):
    """Defect 3. The carry-over tail exists so a fact split across a boundary is
    still readable - a fixed-size need. It must not move when the chunk size
    does."""
    before = ex._compute_prompt_overhead("openai")
    monkeypatch.setattr(ex, "_EXTRACTION_DOC_TOKENS_PER_CALL", 40_000)
    after = ex._compute_prompt_overhead("openai")
    assert before == after, (
        "prompt overhead changed when the chunk size changed - the overlap is "
        "coupled to it again (it was `raw // 7`)"
    )


def test_the_emitted_carry_over_tail_uses_the_constant_not_a_fraction():
    """Defect 3, measured where it actually happens.

    `test_overlap_is_independent_of_chunk_size` above only ever exercised
    `_compute_prompt_overhead` - and that was the ONE site the C31 change
    genuinely fixed. Both functions that EMIT the tail
    (`_chunk_by_sections._flush_cur` and `_split_lines_into_chunks._flush`) kept
    computing `max_chars // 7`, so the constant was reserved in the budget and
    ignored by the code that fills it.

    That is not cosmetic. The chunk size moved 100,000 -> 56,000, so the real
    carry-over silently moved 14,285 -> 8,000 - a 44% cut in the context each
    chunk inherits, while the number of boundaries rose. C31 called itself
    "deliberately behaviour-neutral"; on this axis it was not.

    Measured on the emitted tuples, so a future refactor that reintroduces a
    fraction fails here.
    """
    text = _fixture()
    size = ex._effective_chunk_size("openai")
    chunks = ex._chunk_by_sections(text, size)
    tails = [c[3] for c in chunks[1:] if c[3]]     # chunk 0 has no predecessor
    assert tails, "fixture must produce a multi-chunk split"

    longest = max(len(t) for t in tails)
    # `_tail_chars` trims to the next line break, so a tail is at most the
    # constant and normally within a line of it.
    assert longest <= ex._EXTRACTION_OVERLAP_CHARS
    assert longest > ex._EXTRACTION_OVERLAP_CHARS - 2_000, (
        f"longest emitted carry-over tail is {longest} chars against a declared "
        f"_EXTRACTION_OVERLAP_CHARS of {ex._EXTRACTION_OVERLAP_CHARS}. The chunkers "
        f"are computing their own value again (it was `max_chars // 7`, which at "
        f"the current chunk size gives {size // 7})."
    )


def test_the_reserved_overlap_is_never_smaller_than_the_emitted_one():
    """The budget reserves `_EXTRACTION_OVERLAP_CHARS` for the tail. If a chunker
    ever emits a longer one, every extraction prompt is bigger than the budget
    believes - the C12 failure mode, one step from a context-length 400 and a
    silently blank chunk."""
    text = _fixture()
    for size in (20_000, ex._effective_chunk_size("openai"), 150_000):
        for tail in (c[3] for c in ex._chunk_by_sections(text, size)):
            assert len(tail) <= ex._EXTRACTION_OVERLAP_CHARS, (
                f"emitted a {len(tail)}-char tail at chunk size {size}, but only "
                f"{ex._EXTRACTION_OVERLAP_CHARS} chars are reserved for it"
            )


def test_carry_over_does_not_move_when_the_chunk_size_moves(monkeypatch):
    """The end-to-end version of defect 3: same document, two chunk sizes, the
    tail length must not track the chunk size."""
    text = _fixture()
    tail_at = lambda n: max(                                    # noqa: E731
        (len(c[3]) for c in ex._chunk_by_sections(text, n)), default=0
    )
    small, large = tail_at(30_000), tail_at(120_000)
    # Not byte-equal: `_tail_chars` trims to the next line break, so the exact
    # length depends on where a line happens to fall. One line of slack. Under the
    # old `max_chars // 7` these were 4,285 and 17,142 - a 4x spread, nowhere near
    # this tolerance.
    assert abs(small - large) < 500, (
        f"carry-over tail is {small} chars at a 30k chunk size and {large} at 120k "
        f"- it is a fraction of the chunk size again, not a fixed need"
    )
    for n, got in (("30k", small), ("120k", large)):
        assert got > ex._EXTRACTION_OVERLAP_CHARS - 500, (
            f"tail at {n} is {got}, well under the declared "
            f"{ex._EXTRACTION_OVERLAP_CHARS}"
        )


def test_overlap_pct_is_a_documented_no_op():
    """A third notion of "overlap" (`overlap_pct=0.15`) is passed by
    `_run_extraction` and has never been read. Left in place for positional
    callers, but pinned as inert so nobody wires it up to a fourth meaning."""
    text = _fixture(n_sections=300)
    size = ex._effective_chunk_size("openai")
    assert ex._chunk_by_sections(text, size, 0.0) == ex._chunk_by_sections(text, size, 0.9)


def test_overhead_does_not_recurse_into_chunk_size():
    """`get_chunk_size` is now derived FROM the overhead, so the overhead must not
    call back into it.

    Checked FUNCTIONALLY, not by grepping the source. The first version of this
    test asserted `"get_chunk_size" not in inspect.getsource(...)` and failed on the
    docstring that explains the decoupling - a source-string check cannot tell code
    from prose. If the cycle returns, these calls raise RecursionError.
    """
    assert ex._compute_prompt_overhead("openai") > 0
    assert ex.get_chunk_size("openai") > 0
    assert ex._effective_chunk_size("openai") > 0
    # And the relationship must actually hold.
    assert ex.get_chunk_size("openai") == (
        ex._effective_chunk_size("openai") + ex._compute_prompt_overhead("openai")
    )


# ── No literals left, and coverage still total ───────────────────────────────

def test_the_hand_typed_table_is_gone():
    assert not hasattr(ex, "_MODEL_CHUNK_CHARS"), (
        "the hand-typed _MODEL_CHUNK_CHARS table is back. Chunk size must be "
        "derived from the model spec, not looked up in literals."
    )


@pytest.mark.parametrize("n_sections", [1, 50, 1400])
def test_coverage_is_total_at_the_derived_size(n_sections):
    """Whatever the size, every character must still reach a chunk."""
    text = _fixture(n_sections=n_sections)
    chunks = ex._chunk_by_sections(text, ex._effective_chunk_size("openai"), 100)
    ex._verify_coverage(chunks, len(text), "dec_page")   # raises on any gap
    covered = sum(c[2] - c[1] for c in chunks)
    assert covered == len(text)
