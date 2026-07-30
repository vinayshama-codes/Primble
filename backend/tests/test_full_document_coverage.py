"""Every word of the uploaded documents must reach the LLM.

This is a product requirement, not an optimisation: if a sentence of a
declarations page never reaches the model, the field it would have answered
comes back blank and nobody can tell that from a legitimate omission.

These tests plant unique sentinel tokens throughout a document that is
deliberately LARGER than one call budget - forcing the chunker to split - and
assert every sentinel appears in the text that was actually shipped, for BOTH
hot-path stages:

  * the general field fill  (`_split_raw_text` -> `_build_user_prompt`)
  * the compliance Yes/No pass (`_run_one_compliance_batch`'s own chunker)

READ THIS BEFORE TRUSTING A GREEN RUN HERE. The first version of this file
asserted the same property using a recorder that answered NOTHING. With no field
ever answered, `active_fields` never shrank, the chunk loop never stopped early,
and every chunk always shipped - so the tests passed over a pipeline that was
dropping 46% of a document as soon as a real model answered. A test that only
holds for a silent model proves nothing about production.

So: `_Recorder(answer_fields=True)` is the meaningful configuration, and
`test_an_answering_model_still_gets_the_whole_document` is the test that actually
guards the requirement. The silent-recorder tests below are retained only for the
budget/prefix properties they were also written to cover (C3, C12) - those are
about prompt SHAPE and are independent of what the model replies.

KNOWN AND DELIBERATE GAP, so a green run is not mistaken for more than it is: the
compliance pass stops once every question in a batch is answered and its absorber
is strictly first-wins, so on a multi-chunk document a question answered from
chunk 1 is never rechecked against chunk 3. That is logged as COMPLIANCE_PARTIAL
and is NOT covered by a test here, because fixing it means changing that pass's
merge semantics - see the comment at the break in `_run_one_compliance_batch`.
"""
import json
import os
import threading

import pytest

import services.pdf_service as ps


# Small budgets so a modest document is forced to split, without generating
# megabytes of test data. These are the real env knobs the service reads.
_TEST_BUDGET = 60_000
_TEST_RESERVE = 5_000


@pytest.fixture
def small_budget(monkeypatch):
    # `_effective_budget_chars` is the value `_raw_budget` actually reads - it is
    # seeded from `_GPT_CALL_BUDGET_CHARS` at import and then self-tunes downward
    # on a context-length rejection. Both must be set, and the effective one must
    # be restored, or a shrink from another test leaks into this one.
    monkeypatch.setattr(ps, "_GPT_CALL_BUDGET_CHARS", _TEST_BUDGET)
    monkeypatch.setattr(ps, "_effective_budget_chars", _TEST_BUDGET)
    monkeypatch.setattr(ps, "_GPT_REPLY_RESERVE_CHARS", _TEST_RESERVE)


def _document_with_sentinels(n_sentinels: int = 400) -> tuple:
    """A document whose every paragraph carries a unique, greppable token."""
    parts, sentinels = [], []
    for i in range(n_sentinels):
        tok = f"SENTINEL{i:05d}ZQX"
        sentinels.append(tok)
        parts.append(
            f"POLICY SECTION {i}\n"
            f"Coverage line item {i} - marker {tok} - limit ${1000 + i:,} per occurrence.\n"
            f"Deductible ${500 + i} applies to this item. Endorsement CG {2000 + i} attached.\n"
        )
    return "\n\n".join(parts), sentinels


def _asked_field_names(user: str) -> set:
    """Every ACORD field name the prompt actually asks for.

    THREE renderings, and a recorder that misses any of them silently weakens
    every test in this file:

      `_field_spec`        ->  "  - Producer_FullName_A: Enter text: ..."
      `_slot_group_block`  ->  "  - Insurer_FullName_B [REQUIRED] -> slot 2 of 6 ..."
      `_table_group_block` ->  "  Exact field names per row:"
                               "    _A: Vehicle_CostNewAmount_A, Vehicle_BodyCode_A"

    The table shape is the trap. Its "Columns:" list renders BARE column labels
    ("CityName", "OtherIndicator") on the same `  - x` shape as a real field, so a
    naive `- (\\w+)` regex both invents non-existent keys AND misses every real
    table field. Measured on a 3-form union: 377 of 895 asked fields were invisible
    that way. Since `_absorb` discards unrecognised keys, a recorder that cannot
    answer table fields leaves `active_fields` non-empty forever - so the chunk loop
    never stops early and the coverage assertions pass for the wrong reason. That is
    the same class of blindness as the original always-silent recorder.

    All 5,852 ACORD field names contain an underscore; no column label does.
    """
    import re as _re
    block = user.split("Fields to fill (")[-1]
    names = {f for f in _re.findall(r"^\s+-\s+([A-Za-z0-9_]+)", block, _re.M) if "_" in f}
    for row_line in _re.findall(r"^\s+_[A-N]:\s*(.+)$", block, _re.M):
        for f in row_line.split(","):
            f = f.strip()
            if f and "_" in f and _re.fullmatch(r"[A-Za-z0-9_]+", f):
                names.add(f)
    return names


class _Recorder:
    def __init__(self, answer_fields: bool = False):
        self.answer_fields = answer_fields
        self.calls = []
        self._lock = threading.Lock()
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        msgs = kwargs.get("messages") or []
        system = next((m["content"] for m in msgs if m["role"] == "system"), "")
        user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        # Stage comes from the SYSTEM PROMPT, never from `prompt_cache_key` -
        # that is only sent when the installed SDK supports it, and the deployed
        # venv runs openai==1.54.4, which does not. Keying off it made these
        # tests silently assert "no gap_fill calls were made" on the ship box.
        stage = "compliance" if system is ps._COMPLIANCE_SYSTEM_PROMPT else "gap_fill"
        with self._lock:
            self.calls.append((stage, user))

        # ANSWER the fields when asked to. A recorder that always returns {}
        # never lets `active_fields` shrink, so the chunk loop never stops early
        # and every chunk ships - which is precisely why the original version of
        # this test could not see the early-stop behaviour it was written to
        # guard. See `test_partial_coverage_is_reported_not_hidden`.
        vals = {f: "X" for f in _asked_field_names(user)}
        payload = json.dumps({
            "values": vals, "answers": {}, "quotes": {},
            "raw_text_sourced": [], "question_grounding": {},
        })

        class _R:
            choices = [type("C", (), {"message": type("M", (), {"content": payload})()})()]
            usage = None
        return _R()


def _run_gap_fill(monkeypatch, raw_text, form_id="ACORD_125", max_fields=None):
    rec = _Recorder()
    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: rec)
    path = os.path.join(ps.FORMS_SCHEMAS_DIR, f"{form_id}_schema.json")
    with open(path, encoding="utf-8") as fh:
        schema = json.load(fh)
    facts = {"applicant_name": "Sentinel Test Co"}
    _mapped, unmatched, _ = ps.compute_form_gaps(form_id, schema, facts)
    if max_fields is not None:
        unmatched = dict(list(unmatched.items())[:max_fields])
    ps._fill_unmatched_with_gpt(unmatched, facts, form_id, raw_text=raw_text)
    return rec


# ── The core requirement ─────────────────────────────────────────────────────

def test_every_word_of_a_multi_chunk_document_reaches_the_general_fill(
        monkeypatch, small_budget):
    """No sentence may be dropped when the document exceeds one call budget."""
    raw, sentinels = _document_with_sentinels()
    assert len(raw) > _TEST_BUDGET, "fixture must be big enough to force chunking"

    rec = _run_gap_fill(monkeypatch, raw, max_fields=40)
    shipped = "\n".join(u for st, u in rec.calls if st == "gap_fill")
    assert shipped, "no gap_fill calls were made"

    missing = [s for s in sentinels if s not in shipped]
    assert not missing, (
        f"{len(missing)} of {len(sentinels)} document markers never reached the "
        f"model (first few: {missing[:5]}). The document is being TRUNCATED, not "
        f"chunked - every field those passages would have answered comes back "
        f"blank and looks like a legitimate omission."
    )


def test_every_word_reaches_the_compliance_pass_too(monkeypatch, small_budget):
    """The Yes/No pass chunks the document independently of the general fill.
    A regression in one is invisible from the other."""
    raw, sentinels = _document_with_sentinels()
    rec = _run_gap_fill(monkeypatch, raw, form_id="ACORD_126")
    shipped = "\n".join(u for st, u in rec.calls if st == "compliance")
    assert shipped, "no compliance calls were made (ACORD 126 has 48 Y/N questions)"

    missing = [s for s in sentinels if s not in shipped]
    assert not missing, (
        f"{len(missing)} document markers never reached the compliance pass "
        f"(first few: {missing[:5]}) - Yes/No questions answered by those "
        f"passages will come back blank."
    )


def test_no_prompt_exceeds_the_call_budget(monkeypatch, small_budget):
    """C3's safety property. `_raw_budget` subtracts a CONSTANT fields allowance
    so chunk boundaries stay cacheable; if that constant ever under-reserves, the
    assembled prompt sails past the budget, the call 400s on context length, all
    three retries die, and the batch returns {} - silently blank fields."""
    raw, _ = _document_with_sentinels()
    rec = _run_gap_fill(monkeypatch, raw, max_fields=120)
    assert rec.calls
    ceiling = _TEST_BUDGET - _TEST_RESERVE
    for stage, user in rec.calls:
        total = len(ps._PROMPT_SKELETON) + len(user)
        assert total <= _TEST_BUDGET, (
            f"{stage} prompt is {total:,} chars against a {_TEST_BUDGET:,} budget "
            f"(reply reserve {_TEST_RESERVE:,}, so the intended ceiling is "
            f"{ceiling:,}) - _raw_budget is under-reserving (improving-ll.md C3)"
        )


def test_an_oversized_atomic_batch_still_fits_in_budget(monkeypatch, small_budget):
    """`_pack_field_batches` emits a table group as ONE atomic batch of unbounded
    size. A bare constant allowance (rather than max(constant, actual)) would
    under-reserve for exactly these and blank the whole table."""
    raw, _ = _document_with_sentinels(n_sentinels=120)
    rec = _run_gap_fill(monkeypatch, raw, form_id="ACORD_140")
    assert rec.calls
    for stage, user in rec.calls:
        assert len(ps._PROMPT_SKELETON) + len(user) <= _TEST_BUDGET, (
            f"{stage}: an oversized batch blew the call budget - the "
            f"max(constant, actual) guard in _raw_budget has been removed"
        )


def test_chunk_boundaries_are_identical_across_differently_sized_batches(
        monkeypatch, small_budget):
    """C3 proper: two batches with very different field counts must slice the
    document at the SAME offsets, or their prefixes differ and nothing caches."""
    raw, _ = _document_with_sentinels()

    def _slices(max_fields):
        rec = _run_gap_fill(monkeypatch, raw, max_fields=max_fields)
        out = []
        for stage, user in rec.calls:
            if stage != "gap_fill":
                continue
            marker = "=== RAW DOCUMENT TEXT"
            i = user.index(marker)
            body = user[user.index("\n", i) + 1:]
            body = body[:body.index("\n\nFields to fill (")]
            out.append(body)
        return out

    few, many = _slices(4), _slices(40)
    assert few and many
    assert few[0] == many[0], (
        "a 4-field batch and a 40-field batch sliced the document differently, so "
        "their cached prefixes diverge - _raw_budget is deriving the budget from "
        "the batch's own size again (improving-ll.md C3)"
    )


def _answering_run(monkeypatch, raw, form_id="ACORD_25", n_fields=40):
    rec = _Recorder(answer_fields=True)
    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: rec)
    path = os.path.join(ps.FORMS_SCHEMAS_DIR, f"{form_id}_schema.json")
    with open(path, encoding="utf-8") as fh:
        schema = json.load(fh)
    facts = {"applicant_name": "Sentinel Test Co"}
    _mapped, unmatched, _ = ps.compute_form_gaps(form_id, schema, facts)
    ps._fill_unmatched_with_gpt(
        dict(list(unmatched.items())[:n_fields]), facts, form_id, raw_text=raw)
    return rec


# ── The hole these tests were originally blind to ────────────────────────────

def test_an_answering_model_still_gets_the_whole_document(monkeypatch, small_budget):
    """THE core regression guard, and the one the original version could not make.

    A recorder that answers nothing never lets `active_fields` shrink, so the
    chunk loop never stops early and every chunk always ships - which is why the
    first version of this file "proved" full coverage while production was
    dropping text. With a recorder that ANSWERS, as production does, one 40-field
    batch against a 2-chunk document used to send 1 call and skip 46% of the
    document.

    `_rescan_enabled` now returns True whenever the document actually split, so
    an answering model no longer truncates the scan. Costs nothing on the common
    single-chunk path - there is no second chunk to re-read.
    """
    raw, sentinels = _document_with_sentinels()
    assert len(raw) > _TEST_BUDGET, "fixture must be big enough to force chunking"
    rec = _answering_run(monkeypatch, raw)

    shipped = "\n".join(u for st, u in rec.calls if st == "gap_fill")
    missing = [s for s in sentinels if s not in shipped]
    assert not missing, (
        f"{len(missing)} of {len(sentinels)} document markers never reached the "
        f"model when the model ANSWERED. Early stopping is truncating the scan "
        f"again - check `_rescan_enabled`."
    )


def test_rescan_is_automatic_on_multi_chunk_and_absent_on_single_chunk():
    """The policy itself. Auto must not depend on a human noticing a log line."""
    assert ps._rescan_enabled(1) is False, "nothing to re-scan in a single chunk"
    assert ps._rescan_enabled(2) is True, "a split document must be fully re-scanned"
    assert ps._rescan_enabled(9) is True


def test_single_chunk_run_makes_exactly_one_call_per_batch(monkeypatch):
    """Auto-rescan must cost NOTHING in the common case. A short document is one
    chunk, so there is no second call to make."""
    raw = "DECLARATIONS PAGE\nNamed Insured: Sentinel Test Co\nMARKERAAA\n" * 20
    rec = _answering_run(monkeypatch, raw)
    gap = [u for st, u in rec.calls if st == "gap_fill"]
    assert len(gap) == 1, (
        f"a single-chunk document made {len(gap)} gap_fill calls - auto-rescan is "
        f"charging for chunks that do not exist"
    )


def test_legacy_first_answer_wins_mode_still_reports_partial_coverage(
        monkeypatch, small_budget, caplog):
    """GAP_FILL_FULL_RESCAN=0 is retained only as a kill switch. It measurably
    drops document text, so it must say so - never silently."""
    monkeypatch.setattr(ps, "_GAP_FILL_RESCAN_MODE", "0")
    raw, _ = _document_with_sentinels()
    with caplog.at_level("WARNING", logger="services.pdf_service"):
        _answering_run(monkeypatch, raw)
    assert any("COVERAGE_PARTIAL" in r.message for r in caplog.records), (
        "the legacy mode stopped before consuming every document chunk and said "
        "nothing. Reporting '100% coverage' over a batch that read 62% of the "
        "document is how this went unnoticed."
    )


def test_short_document_is_sent_whole_in_one_chunk(monkeypatch):
    """The common case: a document under budget must go in ONE piece, uncut."""
    raw = "DECLARATIONS PAGE\nNamed Insured: Sentinel Test Co\nUNIQUEMARKERAAA\n" * 20
    rec = _run_gap_fill(monkeypatch, raw, max_fields=40)
    gap = [u for st, u in rec.calls if st == "gap_fill"]
    assert gap
    assert "chunk 1/1" in gap[0], "a short document should not be split at all"
    assert raw.strip()[:200] in gap[0].replace("\r", "")
