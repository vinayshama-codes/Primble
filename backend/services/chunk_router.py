"""Chunk routing for LLM call 2 (gap fill).

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT
---------------------------------------------
This module decides the **ORDER** in which document chunks are offered to a group
of form fields. It never decides **WHICH** chunks a field may see.

That distinction is the whole point, and it is what separates this from
`services/text_selection.py`, which deleted text globally and was set default-OFF
after a live run lost coverage. A global filter is lossy in one direction for
every field at once: drop a window and it is gone for the whole run. Ranking is
lossless by construction - a chunk that ranks last for one field group is still
walked by that group if the group still has blank fields, and is ranked first by
some other group. Nothing is removed from the corpus, ever.

The caller's loop is:

    for chunk in rank_chunks(...):        # best first
        if nothing is still blank: stop
        send (chunk, still-blank fields)

so termination is "every field answered, or every chunk seen". Ranking only moves
the likely answer earlier, which lets the loop stop sooner. If the ranking were
pure noise the loop would degenerate into a full sweep - correct, and costing
roughly what today's single-giant-call design already costs (see
CALL2_RETRIEVAL_REDESIGN.md §3).

TWO SIGNALS
-----------
1. **Fact locations (strong).** LLM call 1 already reads the entire document and
   returns extracted facts. Finding each fact VALUE in the chunk text tells us
   which chunk it was printed in - evidence from having read the page, not a
   keyword guess. We were already paying for that call and throwing the location
   away. `GAP_FILL_ROUTE_BY_FACTS=0` disables it.

2. **IDF-weighted lexical overlap (fallback).** Between a field group's vocabulary
   (its ACORD field names, CamelCase-split, plus its tooltips) and each chunk's
   tokens. A token present in EVERY chunk gets idf 0 and drops out on its own, so
   boilerplate that appears on every page cannot drive the ranking.

No embeddings, no vector store, no extra LLM call, no new dependency. An LLM
ranker would spend a call per group to save a call per group; an embedding index
adds a build step and a failure mode to a pipeline that has enough of both.

Everything here is best-effort. Any failure returns document order, which is
exactly the pre-existing behaviour - a routing bug must never be able to cost a
field its answer.
"""
from __future__ import annotations

import logging
import math
import os
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# ── Knobs (see CALL2_RETRIEVAL_REDESIGN.md §6) ──────────────────────────────
_ROUTING_ENABLED = os.getenv("GAP_FILL_CHUNK_ROUTING", "1").strip().lower() not in (
    "0", "false", "no")
_ROUTE_BY_FACTS = os.getenv("GAP_FILL_ROUTE_BY_FACTS", "1").strip().lower() not in (
    "0", "false", "no")

# A fact value shorter than this is not searched for: too short to locate
# unambiguously, and it would boost a chunk on a coincidence. Same reasoning and
# same value as text_selection's `_FACT_MIN_CHARS`.
_FACT_MIN_CHARS = 4

# How much a located fact outweighs lexical overlap. Deliberately large: a value
# we can SEE printed in a chunk is qualitatively better evidence than a shared
# vocabulary token, and this signal is already sparse (only facts extraction
# actually captured, only those long enough to locate).
_FACT_BOOST = 10.0

# Terms this short carry no retrieval signal and match everywhere ("a", "of").
_MIN_TOKEN_LEN = 3

# English function words and ACORD tooltip INSTRUCTION verbs only.
#
# DELIBERATELY SHORT. The first version of this list also held `name`, `code`,
# `number`, `date`, `text`, `type`, `value`, `item`, `section` - and that was a
# bug caught by `test_field_name_tokens_drop_the_row_suffix`:
# `Vehicle_ManufacturersName_C` tokenised to ['vehicle', 'manufacturers'] with
# the most discriminating token thrown away. Those words are ACORD's core
# vocabulary, not noise.
#
# The list can afford to be short because IDF does the real work: any token that
# appears in EVERY chunk scores exactly 0 and drops out on its own, whatever it
# is. That handles page furniture no hand-written list could anticipate, because
# what counts as boilerplate depends on the document.
_STOPWORDS = frozenset("""
a an the of for to in on at by is are be been was were and or not no if it its
this that these those with from as any all each other such per than then there
here which who whom whose what when where how
enter indicates indicate indicated please provide provided entered choose
applicable used should
""".split())

_CAMEL_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|\d+")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_ROW_SUFFIX_RE = re.compile(r"_[A-N]$")


# ── Tokenisation ────────────────────────────────────────────────────────────
def field_name_tokens(field_name: str) -> List[str]:
    """Split an ACORD field name into lowercase search tokens.

    `Vehicle_ManufacturersName_C` -> ['vehicle', 'manufacturers', 'name']

    The trailing row letter is stripped first: it is a slot index, not a word,
    and `_A` would otherwise tokenise to 'a' on every field in the schema.
    """
    base = _ROW_SUFFIX_RE.sub("", field_name or "")
    out: List[str] = []
    for part in base.split("_"):
        for tok in _CAMEL_RE.findall(part):
            t = tok.lower()
            if len(t) >= _MIN_TOKEN_LEN and t not in _STOPWORDS:
                out.append(t)
    return out


def text_tokens(text: str) -> List[str]:
    """Lowercase word tokens of free text, stopwords and 1-2 char tokens removed."""
    return [
        t for t in (m.group(0).lower() for m in _WORD_RE.finditer(text or ""))
        if len(t) >= _MIN_TOKEN_LEN and t not in _STOPWORDS
    ]


def family_of(field_name: str) -> str:
    """The field's family - the leading underscore segment of its ACORD name.

    Measured on the real 125+126+127 union: 834 fields resolve to 25 families
    (Vehicle 220, Driver 130, GeneralLiabilityLineOfBusiness 71, ...). This is
    free structure that is already in the data; see D4 in the design doc.
    """
    name = field_name or ""
    head = name.split("_", 1)[0]
    return head or name


def group_vocabulary(field_names: Sequence[str],
                     field_meta: Optional[dict] = None) -> Dict[str, float]:
    """Vocabulary of a field group: token -> weight within the group.

    Field-name tokens are weighted above tooltip tokens. A name token is the
    field's identity; a tooltip is ACORD's help text and, measured across the 17
    schemas, is NOT UNIQUE for 4,014 of 5,852 fields (69%) - so it is real signal
    but weaker signal, and must not drown out the name.
    """
    vocab: Dict[str, float] = {}
    meta = field_meta or {}
    for f in field_names:
        for t in field_name_tokens(f):
            vocab[t] = vocab.get(t, 0.0) + 2.0
        info = meta.get(f)
        if isinstance(info, dict):
            tu = info.get("tu") or ""
            # Cap the tooltip contribution: a 500-char tooltip must not let one
            # field outvote the other 39 in its batch.
            for t in text_tokens(tu)[:60]:
                vocab[t] = vocab.get(t, 0.0) + 0.5
    return vocab


# ── The chunk index ─────────────────────────────────────────────────────────
class ChunkIndex:
    """Precomputed per-chunk state, built once per run and reused by every group.

    Building this is O(document); building it per field group would be O(document
    x groups), which on a 13-chunk / 33-group run is 33 pointless passes over
    700k chars.
    """

    __slots__ = ("chunks", "n", "_tokens", "_idf", "_fact_hits")

    def __init__(self, chunks: Sequence[str]):
        self.chunks: List[str] = list(chunks)
        self.n: int = len(self.chunks)
        self._tokens: List[Dict[str, int]] = []
        self._fact_hits: List[Dict[str, int]] = [{} for _ in range(self.n)]

        df: Dict[str, int] = {}
        for body in self.chunks:
            counts: Dict[str, int] = {}
            for t in text_tokens(body):
                counts[t] = counts.get(t, 0) + 1
            self._tokens.append(counts)
            for t in counts:
                df[t] = df.get(t, 0) + 1

        # Classic IDF. A token present in EVERY chunk scores exactly 0 and drops
        # out by itself - which is the property that stops page furniture
        # ("policy", "insured", "coverage", the carrier's name in every footer)
        # from driving the ranking. No stopword list could do that reliably,
        # because what is boilerplate depends on the document.
        self._idf: Dict[str, float] = {}
        for t, d in df.items():
            self._idf[t] = math.log(self.n / d) if d else 0.0

    def index_facts(self, facts: Optional[dict]) -> int:
        """Record which chunk each extracted fact VALUE appears in (signal 1).

        Returns the number of (fact, chunk) locations found, for logging. Only
        deterministic substring search - no model, no cost. Values are matched
        case-insensitively on a whitespace-normalised copy of the chunk so a line
        break inside a value in the PDF text does not hide it.
        """
        if not facts or not _ROUTE_BY_FACTS:
            return 0
        norm_chunks = [re.sub(r"\s+", " ", c).lower() for c in self.chunks]
        found = 0
        for key, value in _flatten_fact_values(facts):
            needle = re.sub(r"\s+", " ", str(value)).strip().lower()
            if len(needle) < _FACT_MIN_CHARS:
                continue
            for ci, hay in enumerate(norm_chunks):
                if needle in hay:
                    hits = self._fact_hits[ci]
                    for t in field_name_tokens(key) or text_tokens(key):
                        hits[t] = hits.get(t, 0) + 1
                    found += 1
        return found

    def score(self, vocab: Dict[str, float], chunk_idx: int) -> float:
        """Relevance of one chunk to one field group's vocabulary."""
        counts = self._tokens[chunk_idx]
        hits = self._fact_hits[chunk_idx]
        total = 0.0
        for term, weight in vocab.items():
            tf = counts.get(term)
            if tf:
                # log-damped term frequency: a chunk mentioning "vehicle" 200
                # times is more relevant than one mentioning it twice, but not
                # 100x more - otherwise a single repetitive page wins everything.
                total += weight * self._idf.get(term, 0.0) * (1.0 + math.log(tf))
            fh = hits.get(term)
            if fh:
                total += _FACT_BOOST * weight * (1.0 + math.log(fh))
        return total


def _flatten_fact_values(facts: dict) -> Iterable[Tuple[str, str]]:
    """Yield (fact_key, scalar_value) for every string-ish value in `facts`.

    Walks one level into lists and dicts so schedule facts (`auto_vin_schedule`
    is a list of row dicts) contribute their VINs, names and plate numbers -
    which are the most locatable, highest-signal strings the extractor produces.
    """
    for key, val in (facts or {}).items():
        if key.startswith("_"):
            continue
        if isinstance(val, str):
            yield key, val
        elif isinstance(val, (int, float)):
            yield key, str(val)
        elif isinstance(val, dict):
            for sub, sv in val.items():
                if isinstance(sv, (str, int, float)):
                    yield f"{key}_{sub}", str(sv)
        elif isinstance(val, list):
            for item in val[:40]:
                if isinstance(item, (str, int, float)):
                    yield key, str(item)
                elif isinstance(item, dict):
                    for sub, sv in item.items():
                        if isinstance(sv, (str, int, float)):
                            yield f"{key}_{sub}", str(sv)


# ── The public entry point ──────────────────────────────────────────────────
def rank_chunks(index: Optional[ChunkIndex],
                field_names: Sequence[str],
                field_meta: Optional[dict] = None,
                label: str = "") -> List[int]:
    """Chunk indices ordered best-first for this field group.

    **ALWAYS returns every chunk index exactly once.** This is a permutation, not
    a selection - the caller walks it until its fields are answered, so returning
    a subset here would silently cap coverage. Guarded by
    `test_rank_chunks_is_always_a_permutation`.

    Falls back to document order on any failure or when routing is disabled.
    """
    if index is None or index.n <= 1:
        return list(range(index.n if index else 0))
    order = list(range(index.n))
    if not _ROUTING_ENABLED:
        return order
    try:
        vocab = group_vocabulary(field_names, field_meta)
        if not vocab:
            return order
        scored = [(index.score(vocab, ci), -ci, ci) for ci in order]
        scored.sort(reverse=True)
        ranked = [ci for _s, _neg, ci in scored]
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "chunk_router: group=%s ranked=%s top_scores=%s",
                label, ranked[:5],
                [round(s, 1) for s, _n, _c in scored[:5]],
            )
        return ranked
    except Exception as ex:                                    # noqa: BLE001
        # Document order is the pre-existing behaviour. A ranking bug must never
        # be able to cost a field its answer.
        logger.warning("chunk_router: ranking failed for %s (%s) - using document "
                       "order", label or "?", ex)
        return order


def build_index(chunks: Sequence[str], facts: Optional[dict] = None,
                label: str = "") -> Optional[ChunkIndex]:
    """Build the per-run chunk index. Returns None if routing cannot be used."""
    try:
        if not chunks:
            return None
        idx = ChunkIndex(chunks)
        located = idx.index_facts(facts)
        logger.info(
            "chunk_router: indexed %d chunk(s) for %s - %d fact location(s) found "
            "(routing=%s, fact_signal=%s)",
            idx.n, label or "gap_fill", located, _ROUTING_ENABLED, _ROUTE_BY_FACTS,
        )
        return idx
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("chunk_router: index build failed (%s) - routing disabled "
                       "for this run", ex)
        return None
