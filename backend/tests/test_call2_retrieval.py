"""LLM call 2 retrieval redesign - see CALL2_RETRIEVAL_REDESIGN.md.

The tests that matter here are the COVERAGE ones. Ranking quality is a
cost/latency property and is allowed to be imperfect; coverage is a correctness
property and is not. Specifically:

  I1  every field is answered, or it has seen every chunk
  I2  every chunk is read, unless every field already has an answer

Both are enforced dynamically (the walk is answer-dependent), so they are tested
by driving the real `combined_gap_fill` with a recording client and asserting on
what the model was actually sent.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

import pytest

os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-real")

import services.pdf_service as ps                                    # noqa: E402
import services.text_selection as ts                                 # noqa: E402
from services import chunk_router as cr                              # noqa: E402

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "forms_schemas"


@pytest.fixture(autouse=True)
def _whole_document(monkeypatch):
    """Production default: text selection OFF, so call 2 sees the whole document.

    DO NOT do this by writing os.environ at module scope. `text_selection` reads
    its flag ONCE at import, and pytest imports every test module before running
    any test - so a module-level `os.environ["GAP_FILL_TEXT_SELECTION"] = "0"`
    here silently disabled the filter for the entire session and took out 12
    tests in test_text_selection.py that had nothing to do with this work. It
    cost a 30-minute suite run to find. Patch the resolved flag, per test.
    """
    monkeypatch.setattr(ts, "_ENABLED", False, raising=False)


# ── Recording client ────────────────────────────────────────────────────────
class _Recorder:
    """Stands in for the sync OpenAI client and records every prompt sent.

    `answer` decides what the fake model returns:
        "none" - answers nothing, so no batch can ever stop early
        "all"  - answers every field it is asked about on the first try
    """

    def __init__(self, answer: str = "none"):
        self.answer = answer
        self.calls: list[tuple[str, str]] = []       # (system, user)
        self._lock = threading.Lock()
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        msgs = kwargs.get("messages") or []
        system = next((m["content"] for m in msgs if m["role"] == "system"), "")
        user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        with self._lock:
            self.calls.append((system, user))
        values = {}
        if self.answer == "all":
            for name in re.findall(r"^\s+- ([A-Za-z0-9_]+)", user, re.M):
                values[name] = "X"
        payload = json.dumps({"values": values, "raw_text_sourced": [],
                              "question_grounding": {}})

        class _M:
            content = payload

        class _C:
            message = _M()

        class _R:
            choices = [_C()]
            usage = None

        return _R()

    # -- helpers the assertions use -------------------------------------------
    # TWO prompt shapes reach the model and both must be parsed here. The general
    # fill emits "=== RAW DOCUMENT TEXT ... ===" then "Fields to fill:" with
    # indented "  - Field" lines; the dedicated compliance pass emits
    # "=== DOCUMENT TEXT ===" then "QUESTIONS —" with unindented "- Field: question"
    # lines. Parsing only the first shape made 12 compliance fields look unasked
    # when they had been asked all along - a test bug that would have been read as
    # a coverage bug.
    _DOC_RE = re.compile(
        r"=== (?:RAW )?DOCUMENT TEXT[^=]*===\n(.*?)"
        r"(?=\n\nFields to fill|\n\nQUESTIONS|\Z)", re.S)

    def document_chunks(self) -> set[str]:
        out = set()
        for _sys, user in self.calls:
            m = self._DOC_RE.search(user)
            if m:
                out.add(m.group(1))
        return out

    def fields_asked(self) -> set[str]:
        out = set()
        for _sys, user in self.calls:
            for marker in ("Fields to fill", "QUESTIONS"):
                if marker in user:
                    block = user.split(marker, 1)[-1]
                    out.update(re.findall(r"^\s*- ([A-Za-z0-9_]+)", block, re.M))
        return out

    def general_fill_batches(self) -> list[list[str]]:
        """Field names per GENERAL-fill call (compliance excluded).

        Family grouping applies to the general fill; the compliance pass has its
        own partition and is out of scope for that assertion.
        """
        out = []
        for _sys, user in self.calls:
            if "Fields to fill" not in user:
                continue
            block = user.split("Fields to fill", 1)[-1]
            out.append(re.findall(r"^\s+- ([A-Za-z0-9_]+)", block, re.M))
        return out


def _big_document(chars: int = 240_000) -> str:
    """A document with distinguishable pages, comfortably over one call budget."""
    pages = []
    i = 0
    while sum(len(p) for p in pages) < chars:
        i += 1
        pages.append(
            f"\n\nPAGE MARKER {i:05d} UNIQUESENTINEL{i:05d}\n"
            "COMMERCIAL GENERAL LIABILITY COVERAGE PART. We will pay those sums the "
            "insured becomes legally obligated to pay as damages because of bodily "
            "injury or property damage to which this insurance applies, subject to "
            "the Each Occurrence Limit shown in the Declarations of this policy.\n"
            + ("filler text for volume. " * 40)
        )
    return "".join(pages)


def _run(forms, raw_text, facts=None, answer="none", monkeypatch=None):
    rec = _Recorder(answer)
    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: rec)
    monkeypatch.setattr(ps, "_COMBINED_BATCH_PAUSE_S", 0.0, raising=False)
    ps.reset_call_budget()
    ps.reset_prefix_warmup()
    facts = facts or {}
    unmatched, mapped = {}, {}
    for fid in forms:
        schema = json.loads((SCHEMA_DIR / f"{fid}_schema.json").read_text(encoding="utf-8"))
        m, u, _ = ps.compute_form_gaps(fid, schema, facts)
        unmatched[fid], mapped[fid] = u, m
    ps.combined_gap_fill(unmatched, facts, raw_text, forms_to_mapped=mapped)
    return rec, unmatched


# ── Router unit tests ───────────────────────────────────────────────────────
def test_rank_chunks_is_always_a_permutation():
    """THE coverage guarantee at the router level.

    The caller walks this list until its fields are answered. If `rank_chunks`
    ever returned a SUBSET, a field could be denied a chunk it never got an
    answer from - silently capping coverage in exactly the way the old global
    text filter did. It must always be a reordering of every index.
    """
    chunks = [f"chunk {i} vehicle vin driver name premium limit" for i in range(9)]
    idx = cr.build_index(chunks, {"applicant_name": "ORBIN CONTRACTING LLC"})
    for fields in (["Vehicle_VINIdentifier_A"],
                   ["Driver_FullName_A", "Driver_LicenseNumber_B"],
                   ["Totally_Unknown_Field_A"],
                   []):
        order = cr.rank_chunks(idx, fields, {}, "t")
        assert sorted(order) == list(range(len(chunks))), fields


def test_rank_chunks_survives_a_broken_index():
    """A ranking failure must degrade to document order, never raise."""
    class _Exploding:
        n = 4

        def score(self, *_a, **_k):
            raise RuntimeError("boom")

    assert cr.rank_chunks(_Exploding(), ["Vehicle_VINIdentifier_A"], {}, "t") == [0, 1, 2, 3]


def test_family_of_matches_the_batcher():
    """The router and the batcher must agree on what a family is (D4)."""
    for name, fam in [("Vehicle_ManufacturersName_C", "Vehicle"),
                      ("NamedInsured_FullName_A", "NamedInsured"),
                      ("Driver_LicensedYear_B", "Driver")]:
        assert cr.family_of(name) == fam
        assert ps._field_family(name) == fam


def test_field_name_tokens_drop_the_row_suffix():
    """`_A` would otherwise tokenise to 'a' on essentially every ACORD field."""
    toks = cr.field_name_tokens("Vehicle_ManufacturersName_C")
    assert toks == ["vehicle", "manufacturers", "name"]
    assert "c" not in toks


def test_fact_location_outranks_lexical_noise():
    """Signal 1 (D3): a chunk that literally contains an extracted value wins.

    Chunk 0 talks about vehicles constantly but holds no real data; chunk 2 holds
    the actual VIN. The vehicle fields must be routed to chunk 2 first.
    """
    chunks = [
        "vehicle vehicle vehicle make model year " * 40,
        "unrelated general liability wording " * 40,
        "SCHEDULE OF COVERED AUTOS  VIN 4S4BRCGC9C3217772  2012 SUBARU OUTBACK",
    ]
    idx = cr.build_index(chunks, {"auto_vin_schedule": [{"vin": "4S4BRCGC9C3217772"}]})
    order = cr.rank_chunks(idx, ["Vehicle_VINIdentifier_A"], {}, "t")
    assert order[0] == 2, order


def test_idf_neutralises_text_present_in_every_chunk():
    """Boilerplate on every page cannot drive the ranking - it scores 0."""
    boiler = "commercial general liability coverage part policy insured "
    chunks = [boiler * 20 + " unique alpha", boiler * 20 + " unique beta"]
    idx = cr.build_index(chunks, {})
    vocab = cr.group_vocabulary(["CommercialGeneralLiability_Policy_Insured_A"], {})
    assert idx.score(vocab, 0) == pytest.approx(idx.score(vocab, 1))


# ── The budget fix (D1) ─────────────────────────────────────────────────────
def test_call2_document_budget_stays_a_small_multiple_of_call_1():
    """The root cause, restated after the 2026-08-13 owner decision.

    THIS TEST WAS WEAKENED, deliberately, and that is worth saying plainly rather
    than burying. It used to read `<= call_1 * 1.05` - "call 2 must not be handed
    more document than call 1 will" - and raising the budget 14,000 -> 28,000
    tokens for cost broke it.

    Deleting it would have thrown away the guard on the ACTUAL defect, which was
    never "call 2 carries more than call 1". It was that call 2 sized itself from
    the CONTEXT WINDOW: 917,000 chars, **16x** call 1, one chunk for a 271-page
    package, 26% fill rate. A small multiple of the proven quality budget is a
    dial; escaping to capacity is a different pipeline.

    So the bound is now explicit and enforced, and `_CALL2_BUDGET_RATIO_MAX` is
    the thing that needs evidence before it moves - not the token count inside it.
    """
    from services.extraction_service import _effective_chunk_size
    call_1 = _effective_chunk_size("openai")
    assert ps._GAP_FILL_DOC_CHARS_PER_CALL <= call_1 * ps._CALL2_BUDGET_RATIO_MAX * 1.05, (
        f"call 2 budget {ps._GAP_FILL_DOC_CHARS_PER_CALL:,} is more than "
        f"{ps._CALL2_BUDGET_RATIO_MAX}x call 1's {call_1:,}")


def test_the_pre_d1_capacity_budget_can_never_come_back():
    """The regression that actually cost the fill rate. 917,000 chars is what the
    context window allows; no ratio this file would accept lets it back in."""
    from services.extraction_service import _effective_chunk_size
    assert ps._CALL2_BUDGET_RATIO_MAX <= 4, "ratio is drifting back toward capacity"
    assert ps._GAP_FILL_DOC_CHARS_PER_CALL < 200_000, (
        "call 2 is being handed a package-sized chunk again - this is the exact "
        "shape of the defect D1 fixed")
    assert _effective_chunk_size("openai") > 0


def test_a_large_document_actually_splits(monkeypatch):
    """Before this change a 700k package went into every call as ONE chunk."""
    doc = _big_document(240_000)
    rec, _ = _run(["ACORD_25"], doc, answer="none", monkeypatch=monkeypatch)
    assert len(rec.document_chunks()) > 1, (
        "the document did not split - call 2 is back to sending the whole package"
    )
    for body in rec.document_chunks():
        assert len(body) <= ps._GAP_FILL_DOC_CHARS_PER_CALL * 1.1


# ── Coverage invariants ─────────────────────────────────────────────────────
def test_I1_every_field_still_reaches_the_model(monkeypatch):
    """No field may be dropped by batching, grouping or routing."""
    doc = _big_document(180_000)
    rec, unmatched = _run(["ACORD_25"], doc, answer="none", monkeypatch=monkeypatch)
    asked = rec.fields_asked()
    expected = set(unmatched["ACORD_25"])
    missing = {f for f in expected if f not in asked and not ps._is_schedule_field(f)}
    assert not missing, f"{len(missing)} field(s) never reached the model: {sorted(missing)[:8]}"


def test_I2_every_chunk_is_read_when_fields_stay_blank(monkeypatch):
    """The model answers nothing, so every chunk must be read by someone."""
    doc = _big_document(180_000)
    rec, _ = _run(["ACORD_25"], doc, answer="none", monkeypatch=monkeypatch)
    canonical = ps._split_text_on_boundaries(doc, ps._GAP_FILL_DOC_CHARS_PER_CALL)
    seen = rec.document_chunks()
    unread = [i for i, c in enumerate(canonical) if c not in seen]
    assert not unread, f"chunk(s) {unread} were never sent to the model"


def test_every_word_of_the_document_reaches_the_model(monkeypatch):
    """Sentinel sweep - the literal version of the owner's requirement.

    Every page carries a unique marker. All of them must appear in some prompt.
    """
    doc = _big_document(180_000)
    rec, _ = _run(["ACORD_25"], doc, answer="none", monkeypatch=monkeypatch)
    sent = "\n".join(u for _s, u in rec.calls)
    markers = set(re.findall(r"UNIQUESENTINEL\d{5}", doc))
    missing = {m for m in markers if m not in sent}
    assert not missing, f"{len(missing)} of {len(markers)} document markers never sent"


def test_unread_chunks_imply_everything_was_answered(monkeypatch):
    """The I2 relationship, stated as a property rather than trusted as a comment.

    A batch stops only when ALL its fields are answered, so a batch holding one
    blank field walks every chunk. Therefore an unread chunk can only exist when
    nothing is blank. This test pins that equivalence: it is what makes the
    sweep's branch unreachable TODAY, and the moment someone caps the walk (an
    obvious future optimisation) this fails and the sweep starts earning its
    keep instead of silently losing pages.
    """
    doc = _big_document(180_000)
    canonical = ps._split_text_on_boundaries(doc, ps._GAP_FILL_DOC_CHARS_PER_CALL)
    assert len(canonical) > 1

    for answer in ("none", "all"):
        rec, unmatched = _run(["ACORD_25"], doc, answer=answer, monkeypatch=monkeypatch)
        seen = rec.document_chunks()
        unread = [i for i, c in enumerate(canonical) if c not in seen]
        if unread:
            # Everything the general fill asked about must have been answered.
            asked = set(rec.fields_asked())
            assert answer == "all", (
                f"{len(unread)} chunk(s) unread while the model answered nothing "
                f"- coverage was lost"
            )
            assert asked, "no fields were asked at all"


def test_full_coverage_is_the_default_even_when_the_model_answers(monkeypatch):
    """D10, the reversal. Coverage must not depend on the model staying silent.

    This mirrors `test_full_document_coverage.py::
    test_an_answering_model_still_gets_the_whole_document` from the routing side:
    ranking reorders the walk, it must not shorten it.
    """
    doc = _big_document(180_000)
    rec, _ = _run(["ACORD_25"], doc, answer="all", monkeypatch=monkeypatch)
    sent = "\n".join(u for _s, u in rec.calls)
    missing = {m for m in re.findall(r"UNIQUESENTINEL\d{5}", doc) if m not in sent}
    assert not missing, (
        f"{len(missing)} document markers never reached the model once it started "
        f"answering - routing is shortening the walk, not just reordering it"
    )


def test_opt_in_early_stop_actually_saves_calls(monkeypatch):
    """The cost knob has to do something, or it is a lie in the docs."""
    doc = _big_document(180_000)
    monkeypatch.setattr(ps, "_ROUTED_EARLY_STOP", True, raising=False)
    rec_stop, _ = _run(["ACORD_25"], doc, answer="all", monkeypatch=monkeypatch)
    monkeypatch.setattr(ps, "_ROUTED_EARLY_STOP", False, raising=False)
    rec_full, _ = _run(["ACORD_25"], doc, answer="all", monkeypatch=monkeypatch)
    assert len(rec_stop.calls) < len(rec_full.calls), (
        f"GAP_FILL_ROUTED_EARLY_STOP changed nothing "
        f"({len(rec_stop.calls)} vs {len(rec_full.calls)} calls)"
    )


# ── Family grouping (D4) ────────────────────────────────────────────────────
def _family_spread(rec) -> tuple[int, int]:
    """(batches spanning >1 family, total general-fill batches)."""
    batches = rec.general_fill_batches()
    spanning = sum(1 for names in batches
                   if len({cr.family_of(n) for n in names}) > 1)
    return spanning, len(batches)


def test_family_grouping_collapses_mixed_batches(monkeypatch):
    """One call, one topic (D4) - measured against the behaviour it replaces.

    NOT asserted as "zero batches span a family", because a detected TABLE bucket
    is indivisible (C19) and its columns legitimately carry different leading
    segments - AdditionalInterest's schedule includes CityName_*, PostalCode_*,
    StateOrProvinceCode_*. Splitting that to satisfy a tidier assertion would
    break row alignment, which is a real correctness property, to improve a
    cosmetic one. So the claim under test is the one that is actually true: the
    number of topically-mixed calls collapses.
    """
    doc = _big_document(120_000)
    rec_on, _ = _run(["ACORD_127"], doc, answer="none", monkeypatch=monkeypatch)
    on_span, on_total = _family_spread(rec_on)

    monkeypatch.setattr(ps, "_GROUP_BATCHES_BY_FAMILY", False, raising=False)
    rec_off, _ = _run(["ACORD_127"], doc, answer="none", monkeypatch=monkeypatch)
    off_span, off_total = _family_spread(rec_off)

    assert off_span > 0, "the baseline has no mixed batches - nothing to improve"
    assert on_span < off_span, (
        f"family grouping did not reduce topically-mixed calls "
        f"({on_span}/{on_total} on vs {off_span}/{off_total} off)"
    )


def test_a_big_family_gets_calls_of_its_own(monkeypatch):
    """Big families pure, small families share - the measured compromise.

    An earlier version of this test asserted that NO batch spans a family. That
    was abandoned deliberately, not quietly: giving every family its own batch
    made the family count the floor on the call count (25-56 families x 13 chunks
    = 897 calls on the 700k / 5-form run), and a 9-field family cannot fill a call
    anyway. The property that survives is the one that carries the quality
    benefit: the families holding most of the fields - Vehicle 220, Driver 130 -
    get calls that are about them and nothing else.
    """
    doc = _big_document(120_000)
    rec, _ = _run(["ACORD_127"], doc, answer="none", monkeypatch=monkeypatch)
    for family in ("Vehicle", "Driver"):
        holding = [names for names in rec.general_fill_batches()
                   if any(cr.family_of(n) == family for n in names)]
        assert holding, f"no batch carried any {family} field"
        pure = [n for n in holding
                if all(cr.family_of(f) == family for f in n)]
        assert len(pure) >= len(holding) * 0.6, (
            f"{family}: only {len(pure)} of {len(holding)} batches were pure - a "
            f"family this size should dominate its own calls"
        )


def test_routing_off_still_covers_every_chunk(monkeypatch):
    """Coverage must not depend on the ranking being enabled."""
    monkeypatch.setattr(cr, "_ROUTING_ENABLED", False, raising=False)
    doc = _big_document(180_000)
    rec, _ = _run(["ACORD_25"], doc, answer="none", monkeypatch=monkeypatch)
    canonical = ps._split_text_on_boundaries(doc, ps._GAP_FILL_DOC_CHARS_PER_CALL)
    seen = rec.document_chunks()
    assert not [i for i, c in enumerate(canonical) if c not in seen]
