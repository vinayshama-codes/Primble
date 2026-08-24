"""Stage A: the declarations index that LLM call 2 reads before the raw document.

WHY THIS EXISTS (CALL2_RETRIEVAL_REDESIGN D11). Measured on the real 271-page
ORBIN package: 30 declarations/schedule pages, 241 pages of ISO/AAIS standard
wording. 11% signal. Gap fill was reading all 271 on every call to find one
address, at 135 calls for a single form.

The index renders the 11% alone, grouped by the section heading each value was
printed under, and gap fill asks it first. What it answers does not walk the raw
document. What it does not answer walks all of it, exactly as before - that is
the guarantee `test_a_field_the_index_cannot_answer_still_sees_every_chunk` pins,
and it is the reason this is an index rather than a replacement.

The two failure modes worth fearing, both tested here:
  * the index SPLITTING (destroys the co-visibility that is its whole point), and
  * a field silently losing its raw-document walk because the index "handled" it.
"""
import json
import os
import re
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.extraction_service as es                          # noqa: E402
import services.pdf_service as ps                                 # noqa: E402
import services.text_selection as ts                              # noqa: E402


@pytest.fixture(autouse=True)
def _whole_document(monkeypatch):
    """Production default: text selection off, so Stage B sees the whole document.

    Patched on the RESOLVED flag, per test - never `os.environ` at module scope.
    `text_selection` reads its env var once at import and pytest imports every
    test module before running any test, so a module-level write here silently
    disables the filter for the entire session. That cost a 30-minute suite run
    to find once already (see test_call2_retrieval.py).
    """
    monkeypatch.setattr(ts, "_ENABLED", False, raising=False)
    monkeypatch.setattr(ps, "_COMBINED_BATCH_PAUSE_S", 0.0, raising=False)
    monkeypatch.setattr(ps, "_DEC_INDEX_ENABLED", True, raising=False)


def _entry(label, value, section=None, owner="policy"):
    return {"label": label, "value": value, "section": section, "owner": owner}


# The C23 shape, in miniature: identical label, different amount, different page.
_C23_ENTRIES = [
    _entry("Each Occurrence Limit", "$3,000,000", "COMMERCIAL UMBRELLA DECLARATIONS"),
    _entry("Aggregate Limit", "$3,000,000", "COMMERCIAL UMBRELLA DECLARATIONS"),
    _entry("Each Occurrence Limit", "$1,000,000", "GENERAL LIABILITY DECLARATIONS"),
    _entry("General Aggregate Limit", "$2,000,000", "GENERAL LIABILITY DECLARATIONS"),
    _entry("Named Insured", "ORBIN CONTRACTING LLC", None, owner="applicant"),
    _entry("Agent Phone", "303-996-7800", None, owner="producer"),
]


# ── 1. What the index says ───────────────────────────────────────────────────

def test_the_same_label_under_two_headings_stays_two_distinct_entries():
    """THE C23 CASE. The umbrella's $3,000,000 and the GL's $1,000,000 are
    sixty-two pages apart under identical labels. Collapsing them, or losing the
    heading, is how a $3M umbrella limit ends up stamped as the GL limit."""
    out = ps._render_dec_index(_C23_ENTRIES)
    assert "[COMMERCIAL UMBRELLA DECLARATIONS]" in out
    assert "[GENERAL LIABILITY DECLARATIONS]" in out
    umbrella = out.split("[COMMERCIAL UMBRELLA DECLARATIONS]")[1].split("[")[0]
    gl = out.split("[GENERAL LIABILITY DECLARATIONS]")[1].split("[")[0]
    assert "Each Occurrence Limit: $3,000,000" in umbrella
    assert "$1,000,000" not in umbrella
    assert "Each Occurrence Limit: $1,000,000" in gl
    assert "$3,000,000" not in gl


def test_both_conflicting_values_are_in_one_call():
    """Co-visibility is the point. Two calls resolved by majority vote is exactly
    the raw-document walk's failure; one call that can see both is the fix."""
    out = ps._render_dec_index(_C23_ENTRIES)
    assert "$3,000,000" in out and "$1,000,000" in out


def test_every_owner_is_rendered_including_other():
    """`owner` is the guard against the producer's phone in the applicant's box.

    REVERSED 2026-08-16. "other" used to be suppressed as "the default, so it
    says nothing". The live 261-entry package disproves that: exactly ONE entry
    carries it, and it is the Drive Other Car named individual - the value that
    has previously been mistaken for a driver and for the applicant. A model
    told "this person is a third party" is better armed than one told nothing.
    """
    out = ps._render_dec_index([
        _entry("Agent Phone", "303-996-7800", None, owner="producer"),
        _entry("Names Of Individuals", "ERIN ROYAL", None, owner="other"),
    ])
    assert "Agent Phone: 303-996-7800  [producer]" in out
    assert "Names Of Individuals: ERIN ROYAL  [other]" in out


# ── The join keys must reach the model, not just the deterministic layer ─────

def _keyed(label, value, section, policy=None, line=None, owner="policy"):
    return {"label": label, "value": value, "section": section, "owner": owner,
            "policy_number": policy, "line_of_business": line}


def test_the_heading_carries_the_policy_and_the_coverage_line():
    out = ps._render_dec_index([
        _keyed("Each Occurrence Limit", "$1,000,000", "GL DECLARATIONS",
               "BBC7263 - 26", "General Liability")])
    assert "[GL DECLARATIONS  |  policy BBC7263 - 26  |  General Liability]" in out


def test_the_underlying_schedule_rows_are_not_read_as_the_umbrella_s():
    """THE CLIENT'S OWN DEFECT SHAPE. The umbrella's underlying-insurance
    schedule prints the GL policy's carrier and number under a heading that says
    UMBRELLA. The entries know better; before this change the rendering did not,
    and the model saw only the heading."""
    out = ps._render_dec_index([
        _keyed("Self Insured Retention", "$ 0", "COMMERCIAL UMBRELLA SCHEDULE",
               "6J7-40-02---26", "Commercial Umbrella"),
        _keyed("Commercial General Liability - Company",
               "EMC Property & Casualty Company", "COMMERCIAL UMBRELLA SCHEDULE",
               "BBC7263 - 26", "General Liability", owner="carrier"),
    ])
    gl_block = out.split("policy BBC7263 - 26")[1]
    assert "General Liability]" in gl_block
    assert "EMC Property & Casualty Company" in gl_block
    # and it is NOT sitting under the umbrella's own heading
    umb = out.split("policy 6J7-40-02---26")[1].split("[")[0]
    assert "EMC Property & Casualty" not in umb


def test_a_missing_key_leaves_the_heading_short_rather_than_borrowing():
    """Blank-over-wrong, applied to the heading. The common declarations page
    genuinely has no single policy - `None` is the honest answer there."""
    out = ps._render_dec_index([
        _keyed("Account Number", "0482854", "Common Declarations", None, None)])
    assert "[Common Declarations]" in out
    assert "policy None" not in out and "|  None" not in out


def test_one_label_value_printed_for_two_policies_stays_two_entries():
    """The de-dup key includes the policy. Keying on (section, label, value)
    alone would keep whichever came first and silently drop the other."""
    out = ps._render_dec_index([
        _keyed("Policy Period", "07/15/25 to 07/15/26", "SCHEDULE", "BBC7263 - 26",
               "General Liability"),
        _keyed("Policy Period", "07/15/25 to 07/15/26", "SCHEDULE", "6E7-40-02---26",
               "Commercial Auto"),
    ])
    assert out.count("Policy Period: 07/15/25 to 07/15/26") == 2


def test_an_entry_missing_its_value_is_dropped_not_rendered_blank():
    """CONTRACT NARROWED 2026-08-23, deliberately.

    A missing VALUE still records nothing and is still dropped. A missing LABEL
    is no longer treated the same way: under the atomic index schema
    `label: null` is how a captionless value is marked, and the case that
    matters is the carrier name printed bare on a declarations masthead -
    `_carriers_by_line` reads owner/value/line and never looks at the label, so
    dropping those entries defeated the carrier rule outright.

    A captionless value renders as a BARE line, never as ": value", which would
    read as an entry whose caption went missing.
    """
    out = ps._render_dec_index([
        _entry("", "$1"), _entry("Label", ""), _entry("Good", "Value")])
    assert "Good: Value" in out
    assert "Label:" not in out, "an entry with no value must not render"
    assert ": $1" not in out, "a captionless value must not render as ': value'"
    assert "$1" in out, "a captionless value is still data and must render bare"


@pytest.mark.parametrize("junk", [None, [], "", 0, [1, 2, 3], [None], {}])
def test_unusable_entries_produce_no_index_rather_than_an_exception(junk):
    """Fail-open at every layer: no index means the pre-2026-08-13 pipeline,
    which is a complete pipeline. An exception here would cost a form its fill."""
    assert ps._render_dec_index(junk) == ""


def test_the_kill_switch_produces_no_index(monkeypatch):
    monkeypatch.setattr(ps, "_DEC_INDEX_ENABLED", False)
    assert ps._render_dec_index(_C23_ENTRIES) == ""


# ── 2. The index must not split ──────────────────────────────────────────────

def test_a_realistic_index_still_fits_in_one_call():
    """One call is still the DESIGN - splitting is the degradation path.

    CONTRACT CHANGED 2026-08-23. This used to assert that a `_DEC_ENTRY_MAX`
    index fits one call, which forced DEC_ENTRY_MAX to stay small enough to fit -
    and a small ceiling DROPS declarations data on a large package. The ceiling
    is now a runaway guard (50,000), and the split was made safe instead (see
    the two tests below). So what is pinned here is the realistic case: an index
    several times larger than any package measured must still arrive in ONE
    call, because co-visibility is free when it fits.

    The largest live package measured produced 227 verified entries. 3,000 is
    over ten times that.
    """
    entries = [
        _entry(f"Label number {i} for a declarations line item", f"Value {i}",
               f"COVERAGE PART {i % 6} DECLARATIONS")
        for i in range(3_000)
    ]
    budget = max(ps._MIN_RAW_CHUNK_CHARS,
                 ps._GAP_FILL_DOC_CHARS_PER_CALL * ps._DEC_INDEX_BUDGET_MULT)
    parts = ps._dec_index_chunks(entries, budget)
    assert len(parts) == 1, (
        f"a 3,000-entry index split into {len(parts)} pieces: "
        f"{len(ps._render_dec_index(entries)):,} chars against a {budget:,} budget. "
        "Raise GAP_FILL_DEC_INDEX_BUDGET_MULT.")


def test_a_split_never_separates_two_entries_sharing_a_label():
    """THE C23 PROPERTY, now guaranteed at any index size.

    The old splitter cut the rendered text by CHARACTER COUNT, so it separated
    the umbrella's $3,000,000 from the GL's $1,000,000 by accident of position -
    identical labels, different coverage parts, resolved by guesswork. The split
    is by LABEL now, so a caption can never straddle two calls.
    """
    entries = []
    for i in range(300):
        entries.append(_entry("Each Occurrence Limit", f"$1,00{i:04d},000",
                              f"COVERAGE PART {i % 9} DECLARATIONS"))
        entries.append(_entry(f"Filler Label {i}", f"Filler Value {i}",
                              f"COVERAGE PART {i % 9} DECLARATIONS"))
    parts = ps._dec_index_chunks(entries, 4_000)
    assert len(parts) > 1, "fixture no longer splits - raise the entry count"
    carrying = [p for p in parts if "Each Occurrence Limit" in p]
    assert len(carrying) == 1, (
        f"'Each Occurrence Limit' was split across {len(carrying)} calls - "
        "the C23 defect is back")


def test_a_split_loses_no_entry_and_duplicates_none():
    """The whole point of removing the entry ceiling is that no declarations
    value is dropped. A splitter that loses or repeats one is worse than the
    ceiling it replaced, so it is pinned here rather than assumed."""
    # Zero-padded to a fixed width so no value is a substring of another -
    # "Value 1" would otherwise match "Value 10" and count 111 false hits.
    entries = [_entry(f"Label {i % 40}", f"Value {i:04d}", f"SECTION {i % 5}")
               for i in range(500)]
    parts = ps._dec_index_chunks(entries, 3_000)
    assert len(parts) > 1, "fixture no longer splits"
    joined = "\n".join(parts)
    for i in range(500):
        assert joined.count(f"Value {i:04d}") == 1, (
            f"'Value {i:04d}' appears {joined.count(f'Value {i:04d}')} times "
            f"across {len(parts)} pieces - expected exactly once")


def test_an_oversized_index_splits_rather_than_building_one_unbounded_call():
    entries = [_entry(f"Label {i}", f"Value {i}", "SECTION") for i in range(400)]
    parts = ps._dec_index_chunks(entries, 3_000)
    assert len(parts) > 1
    for p in parts:
        assert p.startswith(ps._DEC_INDEX_HEADER)
        assert p.endswith(ps._DEC_INDEX_FOOTER)


# ── 3. Section verification (call 1) ─────────────────────────────────────────

_DOC = (
    "GENERAL LIABILITY DECLARATIONS\n"
    "Each Occurrence Limit $1,000,000\n"
    "COMMERCIAL UMBRELLA DECLARATIONS\n"
    "Each Occurrence Limit $3,000,000\n"
)


def test_a_fabricated_section_is_dropped_but_the_entry_survives():
    """A section is an ATTRIBUTION - it says which coverage part owns a figure.
    An invented one is worse than none, so it is dropped on the same verbatim
    rule as label and value. The entry itself is real and must not be lost."""
    out = es._verify_dec_entries(
        [{"label": "Each Occurrence Limit", "value": "$1,000,000",
          "section": "PROFESSIONAL LIABILITY DECLARATIONS", "owner": "policy"}],
        _DOC)
    assert len(out) == 1
    assert out[0]["section"] is None
    assert out[0]["value"] == "$1,000,000"


def test_a_printed_section_survives_verbatim():
    out = es._verify_dec_entries(
        [{"label": "Each Occurrence Limit", "value": "$1,000,000",
          "section": "GENERAL LIABILITY DECLARATIONS", "owner": "policy"}],
        _DOC)
    assert out[0]["section"] == "GENERAL LIABILITY DECLARATIONS"


def test_the_same_label_and_value_under_two_sections_is_not_deduped():
    """Dedup on (label, value) alone would keep whichever heading arrived first
    and silently invent an attribution for the other."""
    out = es._verify_dec_entries([
        {"label": "Each Occurrence Limit", "value": "$1,000,000",
         "section": "GENERAL LIABILITY DECLARATIONS", "owner": "policy"},
        {"label": "Each Occurrence Limit", "value": "$1,000,000",
         "section": "COMMERCIAL UMBRELLA DECLARATIONS", "owner": "policy"},
    ], _DOC)
    assert {e["section"] for e in out} == {
        "GENERAL LIABILITY DECLARATIONS", "COMMERCIAL UMBRELLA DECLARATIONS"}


# ── 4. End-to-end: coverage is not traded away ───────────────────────────────

_BIG_DOC = "\n\n".join(
    f"PAGE {i}\nPolicy wording paragraph {i}. " + ("filler text " * 400)
    for i in range(40)
)


class _Recorder:
    """Answers only the fields named in `answers_for`, so a test can decide
    exactly what the index resolved and what it did not."""

    def __init__(self, index_answers=()):
        self.calls = []
        self.index_answers = set(index_answers)
        self._lock = threading.Lock()
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        msgs = kwargs.get("messages") or []
        user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        with self._lock:
            self.calls.append(user)
        names = re.findall(r"^\s*- ([A-Za-z0-9_]+)", user, re.M)
        vals = {}
        if "=== DECLARATIONS INDEX" in user:
            vals = {n: "FROM_INDEX" for n in names if n in self.index_answers}
        payload = json.dumps({"values": vals, "raw_text_sourced": [],
                              "question_grounding": {}})

        class _R:
            choices = [type("C", (), {"message": type(
                "M", (), {"content": payload})()})()]
            usage = None
        return _R()


_FIELDS = {
    "Producer_FullName_A": {"tu": "Enter text: the producer's full name.", "ft": "/Tx"},
    "NamedInsured_FullName_A": {"tu": "Enter text: the insured's name.", "ft": "/Tx"},
    "Policy_EffectiveDate_A": {"tu": "Enter date: policy effective date.", "ft": "/Tx"},
}
_FACTS = {"dec_page_entries": _C23_ENTRIES}


def _run(monkeypatch, index_answers=()):
    rec = _Recorder(index_answers)
    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: rec)
    monkeypatch.setattr(ps, "_PREFIX_WARMUP", False, raising=False)
    out = ps._fill_unmatched_with_gpt(
        dict(_FIELDS), dict(_FACTS), "ACORD_125", model="gpt-test",
        raw_text=_BIG_DOC, already_filled={}, form_label="ACORD_125")
    return rec, out


def _chunks_of(doc):
    return ps._split_text_on_boundaries(
        doc, max(ps._MIN_RAW_CHUNK_CHARS, ps._GAP_FILL_DOC_CHARS_PER_CALL))


def test_a_field_the_index_cannot_answer_still_sees_every_chunk(monkeypatch):
    """THE GUARANTEE. Stage A is allowed to make the walk shorter by having
    fewer passengers. It is NOT allowed to make the document smaller for a field
    that is still blank - that field's value may be anywhere in the package, and
    "we don't know where the details will be" is the standing requirement."""
    # ANTI-VACUOUS: a fixture that fits in one chunk makes "every chunk was
    # read" trivially true and this test worthless. That trap is C25, and it
    # already burned this codebase once - a coverage test passed over a pipeline
    # dropping 46% of a document. Assert the premise before the conclusion.
    assert len(_chunks_of(_BIG_DOC)) > 1, "fixture no longer splits"
    rec, _ = _run(monkeypatch, index_answers=["Producer_FullName_A"])
    raw_calls = [u for u in rec.calls if "=== RAW DOCUMENT TEXT" in u]
    assert raw_calls
    seen = "".join(u.split("=== RAW DOCUMENT TEXT")[1].split("Fields to fill")[0]
                   for u in raw_calls)
    for i in range(40):
        assert f"PAGE {i}\n" in seen, f"page {i} never reached the model"


def test_an_index_answered_field_leaves_the_raw_walk(monkeypatch):
    """The saving, stated as behaviour: answered by the index means it is not a
    passenger on 13 chunks of raw document."""
    rec, out = _run(monkeypatch, index_answers=["Producer_FullName_A"])
    assert out["filled_values"].get("Producer_FullName_A") == "FROM_INDEX"
    for user in rec.calls:
        if "=== RAW DOCUMENT TEXT" in user:
            assert "- Producer_FullName_A" not in user
            assert "- NamedInsured_FullName_A" in user or \
                   "- Policy_EffectiveDate_A" in user


def test_an_index_that_answers_nothing_costs_only_stage_a(monkeypatch):
    """Worst case must degrade to today's behaviour plus the index calls, never
    to fewer chunks or fewer fields."""
    rec, _ = _run(monkeypatch, index_answers=[])
    raw_calls = [u for u in rec.calls if "=== RAW DOCUMENT TEXT" in u]
    n_chunks = len(_chunks_of(_BIG_DOC))
    assert len(raw_calls) >= n_chunks
    for f in _FIELDS:
        assert any(f"- {f}" in u for u in raw_calls)


def test_stage_a_never_ships_the_raw_document_too(monkeypatch):
    """Carrying both would cost MORE than the behaviour Stage A replaces."""
    rec, _ = _run(monkeypatch, index_answers=["Producer_FullName_A"])
    for user in rec.calls:
        if "=== DECLARATIONS INDEX" in user:
            assert "=== RAW DOCUMENT TEXT" not in user


def test_no_entries_means_no_stage_a_at_all(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: rec)
    monkeypatch.setattr(ps, "_PREFIX_WARMUP", False, raising=False)
    ps._fill_unmatched_with_gpt(
        dict(_FIELDS), {"applicant_name": "Orbin"}, "ACORD_125", model="gpt-test",
        raw_text=_BIG_DOC, already_filled={}, form_label="ACORD_125")
    assert rec.calls
    assert not any("=== DECLARATIONS INDEX" in u for u in rec.calls)


def test_stage_a_reduces_the_raw_call_count(monkeypatch):
    """The cost claim, as an executable assertion rather than a note in an MD."""
    answered, _ = _run(monkeypatch, index_answers=list(_FIELDS))
    unanswered, _ = _run(monkeypatch, index_answers=[])
    n_raw_answered = sum(1 for u in answered.calls if "=== RAW DOCUMENT TEXT" in u)
    n_raw_unanswered = sum(1 for u in unanswered.calls if "=== RAW DOCUMENT TEXT" in u)
    assert n_raw_answered < n_raw_unanswered


# ── 5. Stage A must not break prefix caching ─────────────────────────────────
# improving-ll.md §2 lists five conditions any one of which silently returns this
# pipeline to full price. Adding a whole new call shape is exactly the kind of
# change that trips one of them, so it is asserted rather than assumed.

_MANY_FIELDS = {
    f"Producer_Field{i}_A": {"tu": f"Enter text: producer detail {i}.", "ft": "/Tx"}
    for i in range(120)
}


class _SysRecorder(_Recorder):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.pairs = []

    def create(self, **kwargs):
        msgs = kwargs.get("messages") or []
        self.pairs.append((
            next((m["content"] for m in msgs if m["role"] == "system"), ""),
            next((m["content"] for m in msgs if m["role"] == "user"), ""),
        ))
        return super().create(**kwargs)


def _lcp(strings):
    p = strings[0]
    for s in strings[1:]:
        i = 0
        while i < min(len(p), len(s)) and p[i] == s[i]:
            i += 1
        p = p[:i]
    return p


def _stage_a_run(monkeypatch):
    rec = _SysRecorder()
    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: rec)
    monkeypatch.setattr(ps, "_PREFIX_WARMUP", False, raising=False)
    ps._fill_unmatched_with_gpt(
        dict(_MANY_FIELDS), dict(_FACTS), "ACORD_125", model="gpt-test",
        raw_text=_BIG_DOC, already_filled={}, form_label="ACORD_125")
    return rec


def test_stage_a_does_not_fragment_the_system_prompt(monkeypatch):
    """C2: a per-stage system message diverges at the first tokens, so the ENTIRE
    prompt is billed at full price. Stage A reuses `_PROMPT_SKELETON` precisely so
    it stays in the same cache family as Stage B."""
    rec = _stage_a_run(monkeypatch)
    systems = {s for s, u in rec.pairs if "QUESTIONS" not in u}
    assert len(systems) == 1, f"gap_fill split into {len(systems)} system prompts"


def test_stage_a_calls_share_a_cacheable_prefix(monkeypatch):
    """Stage A's calls all carry the identical index, so all but the first should
    be a cache hit. That only holds if the index sits BEFORE the field list."""
    rec = _stage_a_run(monkeypatch)
    a = [(s, u) for s, u in rec.pairs if "=== DECLARATIONS INDEX" in u]
    assert len(a) > 1, "fixture produced only one Stage A call"
    prefix = len(a[0][0]) + len(_lcp([u for _s, u in a]))
    # OpenAI does not cache below 1024 tokens; ~4 chars/token.
    assert prefix // 4 > 1024, f"Stage A prefix only ~{prefix // 4} tokens"
    # And the divergence must be the field list, not the index.
    assert "=== END DECLARATIONS INDEX ===" in _lcp([u for _s, u in a])
