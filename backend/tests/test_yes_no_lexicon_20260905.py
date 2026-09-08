"""The OPEN half of the Yes/No vocabulary - `services/yes_no_lexicon.py`.

A carrier writes its own forms, so the affirmative half of the vocabulary is
unlistable: `Covered`, `In Force`, `Bound`, `Endorsed`, `Scheduled`, `Written`.
Every word the deterministic table did not hold cost the producer a "please
confirm" card on two documents that agree.

WHAT THESE TESTS ARE ACTUALLY GUARDING. The module asks a model, so the tests
that matter are not "does it learn a word" - they are the four things it is
NOT allowed to do:

  1. never override the deterministic reader
  2. never write a value onto a form
  3. never turn a NON-ANSWER into an answer (core principle 3)
  4. never accept anything it did not ask about, and never guess on failure

Every assertion here drives the real module. The model is stubbed only where a
network call would otherwise happen, and the stub is adversarial on purpose.
"""
import asyncio
import json

import pytest

from services import yes_no_lexicon as lex
from services import fact_equivalence as fe
from services.normalization import yes_no_answer
from services.underwriting_consistency import assess_underwriting_consistency


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Every test gets its own cache. Nothing is written to the real file."""
    monkeypatch.setattr(lex, "_CACHE_PATH", str(tmp_path / "lex.json"))
    monkeypatch.setattr(lex, "_cache", None)
    monkeypatch.setattr(lex, "_refused", set())
    yield
    lex._cache = None
    lex._refused = set()


def _stub(monkeypatch, replies):
    """Stand in for the model. `replies` maps term -> verdict."""
    calls = []

    async def _fake(model, messages, **kw):
        asked = json.loads(messages[-1]["content"])
        calls.append(asked)
        return json.dumps({t: replies.get(t, "unknown") for t in asked})

    import config.settings as cs
    monkeypatch.setattr(cs, "groq_chat", _fake)
    return calls


def _card(fact_key, *values):
    docs = [{"doc_id": str(i), "filename": f"d{i}.pdf", "doc_type": "policy",
             "text": "", "facts": {"applicant_name": "X LLC", fact_key: v}}
            for i, v in enumerate(values)]
    out = assess_underwriting_consistency(docs, dict(docs[0]["facts"]), {})
    return bool([f for f in out["fields"] if f.get("review_required")])


# ── 1. THE DETERMINISTIC READER ALWAYS WINS ─────────────────────────────────

@pytest.mark.parametrize("value", ["Yes", "No", "X", "Y", "N", "Covered",
                                   "Not Covered", "Included", "Excluded"])
def test_a_word_the_deterministic_reader_knows_is_never_asked_about(
        value, monkeypatch):
    """`normalization` is the owner. This module only ever sees the tail."""
    calls = _stub(monkeypatch, {})
    assert yes_no_answer(value) is not None
    assert lex.unknown_terms([value]) == []
    asyncio.run(lex.learn([value]))
    assert calls == [], "the model was asked about a word we already read"


def test_a_learned_word_can_never_contradict_the_deterministic_reader(
        monkeypatch):
    """Even if the model says the opposite, the deterministic answer stands."""
    _stub(monkeypatch, {"yes": "N", "excluded": "Y"})
    asyncio.run(lex.learn(["Yes", "Excluded"]))
    assert fe._yesno_answer("Yes") == "Y"
    assert fe._yesno_answer("Excluded") == "N"


# ── 2. NON-ANSWERS STAY NON-ANSWERS (core principle 3) ──────────────────────

@pytest.mark.parametrize("term", ["applicable", "silent"])
def test_the_pinned_non_answers_cannot_be_promoted_by_any_reply(term, monkeypatch):
    """These two are the words a model is most likely to read as affirmative
    in isolation, and both are non-answers. No reply may classify them."""
    _stub(monkeypatch, {term: "Y"})
    asyncio.run(lex.learn([term]))
    assert lex.lookup(term) is None


@pytest.mark.parametrize("value", ["Not Applicable", "N/A", "None", "TBD",
                                   "Unknown", "Pending", "will confirm"])
def test_an_absence_never_becomes_a_negative(value, monkeypatch):
    """An absence is not a No. If it were, a question that does not apply
    would silently agree with a document that says No.

    THE MODEL IS TOLD THIS AND THE MODEL IS NOT TRUSTED WITH IT. The stub
    below replies "N" for every one of these - the worst case - and
    `_is_classifiable` refuses them all through `answer_semantics`, the door
    that already owns "did they answer?". The first version of this module had
    no such condition and this test failed on all six."""
    _stub(monkeypatch, {lex.normalize_term(value) or "": "N"})
    asyncio.run(lex.learn([value]))
    assert lex.lookup(value) is None
    assert fe._yesno_answer(value) != "N"


@pytest.mark.parametrize("value", ["Not Applicable", "N/A", "TBD", "Unknown"])
def test_a_non_answer_still_reaches_the_producer_as_a_question(
        value, monkeypatch):
    """The consequence that matters: the card still appears.

    "None" is deliberately absent. It is dropped as a MACHINE non-value before
    the comparison ever runs (`underwriting_consistency._normalize`, the H7-D
    fix), so it produces one candidate and no card - which predates this module
    and is a different path. Asserting a card for it here would pin the wrong
    owner."""
    _stub(monkeypatch, {lex.normalize_term(value) or "": "N"})
    asyncio.run(lex.learn([value]))
    assert _card("auto_hired_nonowned", "No", value) is True


# ── 3. WHAT NEVER GOES ON THE WIRE ──────────────────────────────────────────

@pytest.mark.parametrize("value", [
    "$1,000,000", "07/15/2025", "3 vehicles", "44", "BBC7263-26",
    "Marisol Vane, (757) 555-0148, mvane@wexfordmarine.com",
    "Wholesale distribution of marine hardware and boat parts to dealers",
    "", "   ", None,
])
def test_only_short_wordy_terms_are_ever_asked_about(value, monkeypatch):
    """PII, amounts, dates, codes and sentences are refused BEFORE the call.
    That is what makes a process-wide, disk-backed cache safe: the only thing
    it can ever hold is a generic vocabulary word."""
    calls = _stub(monkeypatch, {})
    assert lex.normalize_term(value) is None
    asyncio.run(lex.learn([value]))
    assert calls == []


def test_a_term_is_asked_about_once_however_many_fields_carry_it(monkeypatch):
    calls = _stub(monkeypatch, {"underwritten": "Y"})
    asyncio.run(lex.learn(["Underwritten"] * 40))
    assert calls == [["underwritten"]]
    asyncio.run(lex.learn(["Underwritten"]))
    assert len(calls) == 1, "a cached term was asked about again"


def test_a_refused_term_is_not_asked_about_again(monkeypatch):
    calls = _stub(monkeypatch, {})            # everything comes back "unknown"
    asyncio.run(lex.learn(["Frobnicated"]))
    asyncio.run(lex.learn(["Frobnicated"]))
    assert len(calls) == 1
    assert lex.lookup("Frobnicated") is None


# ── 4. THE MODEL IS NOT TRUSTED WITH THE KEYS ───────────────────────────────

def test_a_reply_about_a_term_we_did_not_ask_about_is_discarded(monkeypatch):
    """A model is free to invent a key. A cache is not free to accept one."""
    async def _fake(model, messages, **kw):
        return json.dumps({"underwritten": "Y", "excluded": "Y",
                           "totally_invented": "Y"})
    import config.settings as cs
    monkeypatch.setattr(cs, "groq_chat", _fake)
    asyncio.run(lex.learn(["Underwritten"]))
    assert lex.lookup("Underwritten") == "Y"
    assert lex.lookup("totally_invented") is None
    assert fe._yesno_answer("Excluded") == "N"     # untouched by the reply


@pytest.mark.parametrize("reply", ["not json at all", "", "[]", "null",
                                   '{"underwritten": "maybe"}',
                                   '{"underwritten": 7}'])
def test_a_bad_reply_learns_nothing_and_raises_nothing(reply, monkeypatch):
    async def _fake(model, messages, **kw):
        return reply
    import config.settings as cs
    monkeypatch.setattr(cs, "groq_chat", _fake)
    assert asyncio.run(lex.learn(["Underwritten"])) == 0
    assert lex.lookup("Underwritten") is None


def test_a_model_failure_falls_back_to_asking_the_producer(monkeypatch):
    """The failure direction. Nothing is learned, so the two values stay
    unequal and the card appears - exactly as before this module existed."""
    async def _boom(model, messages, **kw):
        raise RuntimeError("429")
    import config.settings as cs
    monkeypatch.setattr(cs, "groq_chat", _boom)
    assert asyncio.run(lex.learn(["Underwritten"])) == 0
    assert _card("auto_hired_nonowned", "Underwritten", "X") is True


# ── 5. IT ACTUALLY CLOSES THE HOLE ──────────────────────────────────────────

def test_a_word_nobody_listed_stops_producing_a_false_card(monkeypatch):
    """THE POINT OF THE MODULE. Before: a card. After one learn pass: none.
    And the negative half still disagrees."""
    assert _card("auto_hired_nonowned", "Underwritten", "X") is True
    _stub(monkeypatch, {"underwritten": "Y", "stricken": "N"})
    asyncio.run(lex.learn(["Underwritten", "Stricken"]))
    assert _card("auto_hired_nonowned", "Underwritten", "X") is False
    assert _card("auto_hired_nonowned", "Underwritten", "Stricken") is True
    assert _card("auto_hired_nonowned", "Stricken", "N") is False


@pytest.mark.parametrize("term,verdict", [
    ("in force", "Y"), ("bound", "Y"), ("endorsed", "Y"), ("scheduled", "Y"),
    ("written", "Y"), ("active", "Y"), ("selected", "Y"), ("attached", "Y"),
    ("deleted", "N"), ("removed", "N"), ("void", "N"), ("nil", "N"),
    ("cancelled", "N"), ("lapsed", "N"), ("expired", "N"), ("denied", "N"),
])
def test_the_seed_is_warm_on_a_fresh_install(term, verdict):
    """A brand-new deployment is useful on its first upload, with no call."""
    assert lex.lookup(term) == verdict


# ── 6. THE SHAPE THAT KEEPS IT DETERMINISTIC ────────────────────────────────

def test_the_comparison_path_performs_no_io(monkeypatch):
    """`lookup` is a dict read. If it ever became a call, two runs of one
    package could disagree - which is the property the deterministic-only
    design was protecting, and it is not being given up."""
    async def _boom(model, messages, **kw):        # pragma: no cover
        raise AssertionError("the comparison path called the model")
    import config.settings as cs
    monkeypatch.setattr(cs, "groq_chat", _boom)
    for _ in range(3):
        assert _card("auto_hired_nonowned", "In Force", "X") is False


def test_the_kill_switch_returns_the_system_to_its_previous_behaviour(
        monkeypatch):
    monkeypatch.setattr(lex, "ENABLED", False)
    assert lex.lookup("In Force") is None
    assert lex.unknown_terms(["Underwritten"]) == []
    assert asyncio.run(lex.learn(["Underwritten"])) == 0


def test_the_lexicon_never_reaches_the_form_stamping_path():
    """RULE 2, and the reason this module can be allowed to be wrong. A
    carrier word must not tick an ACORD checkbox on a model's say-so - the
    writer stays deterministic, so the worst this module can do is show or
    hide a CARD."""
    from services.normalization import yes_no_token
    lex._load()["in force"] = "Y"
    assert yes_no_token("In Force") is None
    import services.pdf_service as ps
    assert ps._yes_no_token("In Force") is None


# ── 7. THE SHAPE THE VALUES ACTUALLY ARRIVE IN ──────────────────────────────
# LIVE RUN E FAILED HERE. The collection was inline in `extraction_pipeline`
# and filtered `isinstance(value, str)`, but a per-document fact is an
# ANNOTATED ENVELOPE written by `extraction_service._annotate_facts`. It
# dropped every fact in the package, the model was never asked, and three
# unlisted words produced three conflict cards while 63 unit tests passed -
# because every one of them fed a bare string.
#
# GUESSING THE SHAPE FAILS EXACTLY AS SURELY AS GUESSING THE LAYER.

_ENVELOPE_DOCS = [
    {"filename": "dec.pdf", "facts": {
        "hired_auto_indicator": {"value": "Underwritten",
                                 "confidence": "ai_high"},
        "non_owned_auto_indicator": {"value": "Issued",
                                     "confidence": "ai_high"},
        "cyber_prior_incidents": {"value": "Withdrawn",
                                  "confidence": "ai_high"},
        "applicant_name": {"value": "Halloway Facility Services LLC",
                           "confidence": "ai_high"},
        "annual_revenue": {"value": "$5,480,000", "confidence": "ai_high"}}},
    {"filename": "coi.pdf", "facts": {
        "hired_auto_indicator": "Y",
        "non_owned_auto_indicator": "X",
        "cyber_prior_incidents": "N"}},
]


def test_the_annotated_envelope_is_unwrapped():
    """THE LIVE RUN E REGRESSION. Both shapes, in one package."""
    got = lex.terms_from_documents(_ENVELOPE_DOCS)
    assert "Underwritten" in got and "Issued" in got and "Withdrawn" in got
    assert "Y" in got and "X" in got and "N" in got


def test_only_yes_no_fields_are_collected():
    """A name and an amount live in the same facts dict and must never be
    offered as vocabulary - that is the first half of keeping PII off the
    wire, before `normalize_term` ever sees them."""
    got = lex.terms_from_documents(_ENVELOPE_DOCS)
    assert "Halloway Facility Services LLC" not in got
    assert "$5,480,000" not in got


@pytest.mark.parametrize("docs", [
    None, [], [None], [{}], [{"facts": None}], [{"facts": "not a dict"}],
    [{"facts": {"hired_auto_indicator": None}}],
    [{"facts": {"hired_auto_indicator": {"confidence": "x"}}}],
    [{"facts": {"hired_auto_indicator": {"value": ""}}}],
])
def test_a_malformed_document_collects_nothing_and_raises_nothing(docs):
    assert lex.terms_from_documents(docs) == []


def test_run_e_end_to_end(monkeypatch):
    """The live failure, driven from the document shape the pipeline builds.

    Before the fix this asked about nothing and produced three cards."""
    assert lex.unknown_terms(lex.terms_from_documents(_ENVELOPE_DOCS)) == [
        "underwritten", "issued", "withdrawn"]
    _stub(monkeypatch, {"underwritten": "Y", "issued": "Y", "withdrawn": "N"})
    assert asyncio.run(lex.learn(lex.terms_from_documents(_ENVELOPE_DOCS))) == 3
    assert _card("hired_auto_indicator", "Underwritten", "Y") is False
    assert _card("non_owned_auto_indicator", "Issued", "X") is False
    assert _card("cyber_prior_incidents", "Withdrawn", "N") is False
    # ...and the opposite pair must still disagree (package F's control).
    assert _card("hired_auto_indicator", "Underwritten", "Withdrawn") is True


def test_the_call_site_does_not_reimplement_the_collection():
    """ANTI-ROT. The inline copy is what broke; one owner is the fix."""
    import inspect
    import services.extraction_pipeline as ep
    src = inspect.getsource(ep._finalize_pipeline)
    assert "terms_from_documents" in src
    assert "isinstance(_v, str)" not in src, (
        "the call site is filtering fact values again - that is the live run E "
        "defect")


# ── 8. THE QUESTION WE ASK IS POLARITY, NOT ANSWER-MATCHING ─────────────────
# Two frames were tried live and both were REFUSED BY THE MODEL, correctly:
#   round 1  a bare word, "what does this mean as an answer on a form?"
#            -> `Underwritten` and `Issued` refused; out of context "issued"
#               could as easily describe the POLICY being issued.
#   round 2  the word plus the question its box answers, from FACT_REGISTRY
#            -> refused again, and rightly: `hired_auto_indicator` is
#               registered as "Do employees drive hired or rented vehicles for
#               business purposes?", an EXPOSURE question that "Underwritten"
#               does not answer. Real context, WRONG context.
# The frame was wrong both times, not the model. The comparison only ever asks
# whether two values mean the SAME THING, so the question is the polarity of
# the word - which is also what licenses caching by the word.

def test_the_prompt_asks_for_polarity_and_not_for_an_answer():
    """ANTI-ROT. Re-framing this as answer-matching is what failed twice."""
    assert "POLARITY" in lex._SYSTEM
    assert "ASSERTS" in lex._SYSTEM
    # ...and it must keep telling the model that a non-answer is never an "N".
    assert "never" in lex._SYSTEM and "Not applicable" in lex._SYSTEM


def test_the_ask_carries_no_per_document_context():
    """A term is judged as VOCABULARY, independently of the box it landed in.
    That is the same property that makes the shared cache correct: if the
    answer depended on the question, one cache entry could not serve every
    package."""
    import inspect
    src = inspect.getsource(lex.learn)
    assert "json.dumps(asked)" in src, (
        "the payload carries something other than the terms - if that is "
        "per-document context, the cache key is no longer sufficient")


def test_the_polarity_frame_classifies_what_the_other_frames_refused(
        monkeypatch):
    """The live regression, with the model's real verdicts recorded.

    Measured against the live model on 2026-09-05, one call, 19 terms: every
    affirmative Y, every negative N, and every non-answer plus an amount, a
    date and a person's name "unknown" - 19/19, where the two earlier frames
    scored 1/4."""
    _stub(monkeypatch, {"underwritten": "Y", "issued": "Y", "placed": "Y",
                        "withdrawn": "N", "stricken": "N", "forgone": "N"})
    docs = [{"facts": {
        "hired_auto_indicator": {"value": "Underwritten"},
        "non_owned_auto_indicator": {"value": "Issued"},
        "cyber_prior_incidents": {"value": "Withdrawn"},
        "sprinkler_system": {"value": "Placed"}}}]
    assert asyncio.run(lex.learn(lex.terms_from_documents(docs))) == 4
    assert _card("hired_auto_indicator", "Underwritten", "Y") is False
    assert _card("non_owned_auto_indicator", "Issued", "X") is False
    assert _card("cyber_prior_incidents", "Withdrawn", "N") is False
    assert _card("sprinkler_system", "Placed", "Yes") is False
    # package F's control: opposite polarities must still disagree
    assert _card("hired_auto_indicator", "Underwritten", "Stricken") is True
