"""What does this word MEAN on a Yes/No field? - the open half of SYS-07.

THE PROBLEM THIS EXISTS FOR, stated plainly.
A declarations page does not print "Yes". It prints the coverage status in the
carrier's own words: `Covered`, `Elected`, `Provided`, `In Force`, `Bound`,
`Endorsed`, `Afforded`, `Scheduled`, `Written`. There is no end to that list -
every carrier writes its own forms - so `normalization`'s deterministic table
can never be complete, and each word it does not know costs the producer a
"please confirm" card on two documents that agree.

THE TWO SIDES ARE NOT SYMMETRIC, and that asymmetry is the whole design:

  * AFFIRMATIVES ARE OPEN. Anything that asserts the coverage is there.
    Unlistable.
  * NEGATIVES ARE NEARLY CLOSED. English says no in a handful of ways -
    not / no / non / un- / ex-, plus excluded, declined, waived, rejected,
    void, deleted, cancelled, lapsed. Finite, and therefore closable.

So this module NEVER guesses an affirmative into existence on its own. It asks
the model that has ALREADY READ THE DOCUMENT what the word means, caches the
answer by the word, and refuses anything it is not sure about.

WHAT IT IS NOT ALLOWED TO DO
----------------------------
1. **It never overrides the deterministic tables.** `normalization` answers
   first, always. This module only ever sees what that could not read.
2. **It never writes a value onto a form.** The ONLY consumer is the
   comparison layer's question *"do these two documents agree?"*. A wrong
   answer here costs a card that should not have appeared or one that should
   have - never a wrong value on a legal document. `pdf_service`'s checkbox
   writer and `_yn_gate` stay deterministic, deliberately.
3. **Unsure is an answer.** The prompt is required to return "unknown" freely
   and every failure path returns None, which means "compare it as text" -
   i.e. the producer still gets the card. Fail toward asking.
4. **It never sees a document.** Only single short values already extracted
   into a Yes/No FIELD, capped at `_MAX_TERM_CHARS` and `_MAX_TERM_WORDS`.
   That keeps PII out of the cache and off the wire, and it is why the cache
   can be process-wide and disk-backed: "Covered" means the same thing in
   every package, for every customer.

WHY A CACHE, AND WHY IT IS SAFE TO SHARE
----------------------------------------
The answer depends on the WORD alone, never on the document, the applicant or
the package. So one lookup serves every session that ever meets that word, the
cost converges to zero, and two runs of the same package give the same answer -
which is what the deterministic-only design was protecting in the first place.

Kill switch: ``YES_NO_LEXICON=0`` returns this module to a pure no-op, and the
system behaves exactly as it did before it existed.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "lookup", "learn", "learn_sync", "unknown_terms", "normalize_term",
    "cache_snapshot", "terms_from_documents", "ENABLED",
]

ENABLED = os.getenv("YES_NO_LEXICON", "1") not in ("0", "false", "False")

# A Yes/No box holds an ANSWER, not a sentence. Anything longer is either a
# qualified answer (which must keep its words and be compared as text) or a
# mis-extraction - neither is a vocabulary question, and both are exactly what
# we must not put on the wire.
_MAX_TERM_CHARS = 40
_MAX_TERM_WORDS = 4
_MAX_TERMS_PER_CALL = 40

_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "yes_no_lexicon.json")

_lock = threading.RLock()
_cache: Optional[Dict[str, str]] = None
# Terms the model was asked about and could not classify. Held so a package
# with the same unreadable word on 40 fields asks once, not forty times, and
# so a second run does not re-ask what was already refused.
_refused: set = set()

# ── SEED: the words the model was asked about during development, kept so a
# fresh install is useful on its first run and so the common case never needs
# a call at all. NOT a replacement for the model - it is a warm cache, and
# every entry here is also derivable by asking.
_SEED: Dict[str, str] = {
    "in force": "Y", "inforce": "Y", "bound": "Y", "attached": "Y",
    "endorsed": "Y", "scheduled": "Y", "written": "Y", "selected": "Y",
    "active": "Y",
    "yes x": "Y", "confirmed": "Y", "accepted": "Y", "agreed": "Y",
    "deleted": "N", "removed": "N", "void": "N", "nil": "N",
    "cancelled": "N", "canceled": "N", "lapsed": "N", "expired": "N",
    "suspended": "N", "denied": "N", "omitted": "N",
    # PINNED UNCLASSIFIABLE - see below.
    "applicable": None, "silent": None, "pending": None,
}
# `applicable`, `silent` and `pending` are pinned to None ON PURPOSE. They are the two
# words most likely to be classified as an affirmative by a model reading them
# in isolation, and both are non-answers: "Not Applicable" says the question
# does not apply (core principle 3) and "silent" says the policy does not
# address it. Pinning them here means no model reply can promote them.

_WORD_RE = re.compile(r"[A-Za-z]")


def normalize_term(value: Any) -> Optional[str]:
    """The cache key for a value, or None when it must never be asked about.

    Lower-cased, whitespace-collapsed, stripped of the punctuation a form
    prints around an answer. Returns None for anything that is not a short
    wordy term - a number, an amount, a date, a sentence, an empty box.
    """
    s = str(value or "").strip().strip(" \t\r\n.,;:!*_'\"`[]()<>{}")
    s = " ".join(s.split()).lower()
    if not s or len(s) > _MAX_TERM_CHARS or len(s.split()) > _MAX_TERM_WORDS:
        return None
    if not _WORD_RE.search(s):
        return None                      # a number, a code, a mark - not a word
    # A term that carries a digit is a value, not a vocabulary word
    # ("3 vehicles", "$1,000,000", "07/15/2025").
    if any(ch.isdigit() for ch in s):
        return None
    return s



def _is_classifiable(term: str) -> bool:
    """May this term be given a Yes/No meaning AT ALL?

    STRUCTURAL, NOT A PROMPT INSTRUCTION. The prompt already tells the model
    that a non-answer is "unknown", and H1-K is the standing proof that a
    prompt is not a guarantee - there, an extractor returned a payroll PERIOD
    the document never named and the rule that depended on it could never
    fire. The first version of this module had the same hole: a reply saying
    *"Not Applicable = N"* was accepted, and an absence became a NEGATIVE -
    core principle 3, the exact inversion SYS-07 exists to prevent. My own
    test caught it before it shipped.

    So the question is asked of the door that already owns it.
    ``answer_semantics.interpret_answer`` separates *"what is the value?"* from
    *"did they answer?"*; anything it does not call a PRESENT value - an
    absence ("None"), an inapplicability ("N/A", "Not Applicable"), or a
    non-answer ("TBD", "unknown", "will confirm") - can never be a vocabulary
    word here, whatever any model replies.

    The fact key is a representative Yes/No fact rather than the caller's:
    a term is being judged as VOCABULARY, independently of which box it landed
    in, which is the same reason the cache can be shared at all.
    """
    try:
        from services.answer_semantics import interpret_answer
        r = interpret_answer(_PROBE_FACT, term)
        return bool(getattr(r, "value_state", "") == "present"
                    and str(getattr(r, "value", "") or "").strip())
    except Exception:                                        # pragma: no cover
        # Cannot ask the door -> do not classify. Fail toward the card.
        return False


_PROBE_FACT = "auto_hired_nonowned"


def _load() -> Dict[str, str]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        data: Dict[str, str] = {}
        try:
            with open(_CACHE_PATH, encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                data = {str(k): v for k, v in raw.items() if v in ("Y", "N")}
        except FileNotFoundError:
            pass
        except Exception as exc:                              # noqa: BLE001
            logger.warning("yes_no_lexicon: cache unreadable (%s) - starting "
                           "empty; nothing else is affected", exc)
        # The seed never loses to a stored value: the two pinned non-answers
        # must stay unclassifiable however a past reply was recorded.
        for k, v in _SEED.items():
            if v is None:
                data.pop(k, None)
            else:
                data.setdefault(k, v)
        _cache = data
        return _cache


def _persist() -> None:
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        tmp = _CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_load(), fh, indent=1, sort_keys=True)
        os.replace(tmp, _CACHE_PATH)
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("yes_no_lexicon: could not persist cache (%s) - the "
                       "lookup still works for this process", exc)


def lookup(value: Any) -> Optional[str]:
    """``"Y"`` / ``"N"`` / ``None`` for one already-extracted value.

    PURE AND SYNCHRONOUS - a dict read, no network, no event loop. This is the
    only function the comparison path calls, which is what keeps `same_fact`
    free of I/O and keeps two runs of one package identical.
    """
    if not ENABLED:
        return None
    term = normalize_term(value)
    if not term:
        return None
    if term in _SEED and _SEED[term] is None:
        return None
    return _load().get(term)


def unknown_terms(values: Iterable[Any]) -> List[str]:
    """The subset of ``values`` that is worth asking the model about.

    Deterministic readers first, cache second, and anything already refused is
    never asked twice.
    """
    if not ENABLED:
        return []
    try:
        from services.normalization import yes_no_answer
    except Exception:                                         # pragma: no cover
        def yes_no_answer(_v):
            return None
    seen: List[str] = []
    cache = _load()
    for v in values or ():
        term = normalize_term(v)
        if not term or term in cache or term in _refused or term in seen:
            continue
        if _SEED.get(term, "") is None:
            continue
        if yes_no_answer(v):
            continue                     # the deterministic reader already has it
        if not _is_classifiable(term):
            continue                     # an absence / non-answer is not vocabulary
        seen.append(term)
        if len(seen) >= _MAX_TERMS_PER_CALL:
            break
    return seen


# ── THE QUESTION WE ASK, AND THE TWO WRONG ONES WE ASKED FIRST ──────────────
# Round 1 handed the model a bare word and asked what it meant as an answer on
# an insurance form. It refused `Underwritten` and `Issued` - live run E,
# *"asked 3 term(s), learned 1, refused 2"* - and it was right to: rule 1 says
# unknown is always safe, and out of context "issued" could as easily describe
# the POLICY being issued as the coverage being elected.
#
# Round 2 added the question the box answers, from `FACT_REGISTRY`. It refused
# the same two, and was right again - `hired_auto_indicator`'s registered
# question is *"Do employees drive hired or rented vehicles for business
# purposes?"*, which is an EXPOSURE question, and "Underwritten" does not
# answer it. The context was real and it was the WRONG CONTEXT.
#
# The frame was wrong both times, not the model. This layer never needed to
# know what the term answers - the comparison only asks whether two values mean
# the SAME THING, so the question is POLARITY: does this word assert presence
# or absence? That is a property of the word alone, which is also exactly what
# licenses caching by the word.
#
# Measured against the live model, 19 terms, one call: every affirmative Y,
# every negative N, and every non-answer - "not applicable", "pending", "tbd",
# "none", "silent", "see schedule" - plus an amount, a date and a person's name
# all "unknown". 19/19, where the previous two frames scored 1/4.
_SYSTEM = (
    "You judge the POLARITY of single words and short phrases as they are "
    "printed in the answer box of an insurance form.\n\n"
    "For each term answer exactly one of:\n"
    "  \"Y\"       - the term ASSERTS that something is present, granted, "
    "active, elected, agreed or true\n"
    "  \"N\"       - the term ASSERTS that something is absent, removed, "
    "refused, ended or false\n"
    "  \"unknown\" - the term asserts NEITHER, including anything meaning "
    "the question does not apply, is not stated, is not yet decided, or is a "
    "quantity, amount, date, name or code\n\n"
    "This is a judgement about the WORD, not about any particular question. "
    "\"Covered\", \"Elected\", \"Issued\", \"Placed\", \"Underwritten\", "
    "\"In Force\" all assert presence. \"Excluded\", \"Declined\", "
    "\"Withdrawn\", \"Stricken\", \"Void\" all assert absence.\n"
    "IMPORTANT: \"Not applicable\", \"N/A\", \"none\", \"TBD\", "
    "\"pending\", \"unknown\", \"see schedule\" and \"silent\" assert "
    "NEITHER and must be \"unknown\", never \"N\".\n\n"
    "Reply with ONLY a JSON object mapping each term to \"Y\", \"N\" or "
    "\"unknown\". No prose."
)


def _absorb(reply: str, asked: List[str]) -> int:
    """Record a model reply. Returns how many terms were newly classified."""
    try:
        s, e = reply.find("{"), reply.rfind("}")
        data = json.loads(reply[s:e + 1]) if s != -1 and e != -1 else {}
    except Exception:                                         # noqa: BLE001
        logger.warning("yes_no_lexicon: unparseable reply - nothing learned")
        return 0
    if not isinstance(data, dict):
        return 0
    added = 0
    cache = _load()
    asked_set = set(asked)
    with _lock:
        for term, verdict in data.items():
            key = normalize_term(term)
            # ONLY what we asked about. A model is free to invent a key; a
            # cache is not free to accept one.
            if not key or key not in asked_set:
                continue
            v = str(verdict or "").strip().upper()[:1]
            if v in ("Y", "N") and _SEED.get(key, "") is not None                     and _is_classifiable(key):
                cache[key] = v
                added += 1
            else:
                _refused.add(key)
        for term in asked_set:
            if term not in cache:
                _refused.add(term)
    if added:
        _persist()
    logger.info("yes_no_lexicon: asked %d term(s), learned %d, refused %d",
                len(asked), added, len(asked) - added)
    return added



def terms_from_documents(docs: Any) -> List[Any]:
    """Every Yes/No value printed by any document in a package.

    THE COLLECTION IS OWNED HERE, NOT AT THE CALL SITE, and that is a scar.
    The first version lived inline in `extraction_pipeline` and filtered
    `isinstance(value, str)` - but a per-document fact is an ANNOTATED
    ENVELOPE (`{"value": ..., "confidence": ...}`, written by
    `extraction_service._annotate_facts`), so the filter dropped every fact in
    the package and the model was never asked. Live run E proved it: three
    unlisted words, three conflict cards, and no cache file written at all.

    That is the fourth time in a week that a correct rule was defeated by the
    layer it was wired into - guess the SHAPE and you fail exactly as surely as
    guessing the LAYER. So the unwrap now happens beside the rule, once, and
    `tests/test_yes_no_lexicon_20260905.py` drives it with the real envelope
    shape rather than a convenient string.
    """
    out: List[Any] = []
    try:
        from services.normalization import is_yes_no_field
    except Exception:                                        # pragma: no cover
        return out
    for doc in docs or ():
        facts = (doc or {}).get("facts") if isinstance(doc, dict) else None
        if not isinstance(facts, dict):
            continue
        for key, value in facts.items():
            if not is_yes_no_field(key):
                continue
            if isinstance(value, dict) and "value" in value:
                value = value.get("value")
            if isinstance(value, str) and value.strip():
                out.append(value)
    return out


async def learn(values: Iterable[Any]) -> int:
    """Classify every value the deterministic readers could not, once.

    Never raises. On any failure nothing is learned and every affected value
    keeps producing a "please confirm" card, which is the behaviour that
    existed before this module.
    """
    if not ENABLED:
        return 0
    asked = unknown_terms(values)
    if not asked:
        return 0
    try:
        from config.settings import groq_chat, LLM_MODEL
        reply = await groq_chat(
            LLM_MODEL,
            [{"role": "system", "content": _SYSTEM},
             {"role": "user", "content": json.dumps(asked)}],
            temperature=0, max_tokens=600)
        return _absorb(reply or "", asked)
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("yes_no_lexicon: learn failed (%s) - unreadable terms "
                       "stay unreadable and the producer is still asked", exc)
        return 0


def learn_sync(values: Iterable[Any]) -> int:
    """`learn` from a synchronous worker thread. Same guarantees."""
    if not ENABLED:
        return 0
    try:
        if not unknown_terms(values):
            return 0
        import asyncio
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(learn(values))
        # A loop is already running on this thread: hand the work to one that
        # is not, rather than blocking the caller's loop.
        import concurrent.futures as _cf
        with _cf.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run,
                               learn(values)).result(timeout=120)
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("yes_no_lexicon: learn_sync failed (%s)", exc)
        return 0


def cache_snapshot() -> Dict[str, str]:
    """A copy of what is known. For tests and for answering "what did it
    learn from the client's documents?" without opening the file."""
    return dict(_load())
