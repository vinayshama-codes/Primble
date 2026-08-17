"""narrative_facts.py - read the facts INSIDE a remarks paragraph, in context.

CLIENT, 2026-08-17: *"Additional Remarks has a similar issue. A paragraph
containing policy numbers, dates, limits, premiums, exclusions, etc. should not
be treated as one competing value. The individual facts within it need to be
interpreted in their appropriate context."*

Two halves. The first - stop asking "which paragraph is correct?" - is handled
by ``fact_equivalence``: prose is INCOMPARABLE, so two remarks blocks are kept
and neither is escalated. This module is the second half: the paragraph carries
real data, and today all of it is invisible.

    "The Commercial Umbrella limit under policy 6J7-40-02---26 was reduced
     from $3,000,000 to $1,000,000 effective 07/25/2025."

── WHY THIS IS NOT "PULL THE NUMBERS OUT" ───────────────────────────────────
Probe run B proved what naive mining does. Extraction lifted ``07/25/2025`` out
of that very sentence and stored it as the UMBRELLA'S EFFECTIVE DATE. It is an
ENDORSEMENT date - the day an amendment took effect - and the policy still
incepted on 07/15/2025. A number inside a sentence is not a value; it is part of
a STATEMENT, and the statement is what carries the meaning.

So this module never emits facts. It emits **statements**:

    {subject: "umbrella_limit", from: "$3,000,000", to: "$1,000,000",
     as_of: "07/25/2025", policy_number: "6J7-40-02---26", quote: "<verbatim>"}

── WHY DETERMINISTIC AND NOT AN LLM ─────────────────────────────────────────
Measured on three real Orbin packages: 188, 1077 and 1288 characters of
narrative. An LLM pass would be nearly free, and was the first design. It was
not taken, for a better reason than cost: the subject of every statement here
must be a fact key we already own, and the amounts must be strings the document
literally printed. Both are lookups against tables that already exist
(``arq_service._FIELD_PRODUCER_LABEL_MAP``, plus the package's OWN dec-index
labels, which are the document teaching us its vocabulary). A model adds the one
failure this feature cannot afford - an invented subject - to solve a problem
that is already a lookup.

The honest limit of that choice is recorded at the bottom of this file: claim
rows and exclusion clauses are NOT mined here, because those genuinely need
language understanding rather than a lookup. They remain scoped work.

── WHAT CONSUMES A STATEMENT ────────────────────────────────────────────────
Deliberately NOT the fact store, and deliberately NOT the picker's answer. The
client also said *"an unresolved fact must remain unresolved downstream rather
than another part of Primble independently selecting a value"* - so a statement
never resolves a conflict. It EXPLAINS one:

    Umbrella limit - confirm
      $3,000,000  (dec page)   vs   $1,000,000  (certificate)
      The remarks state this was reduced from $3,000,000 to $1,000,000
      effective 07/25/2025.

The producer settles it in one click instead of digging through 271 pages. That
is "escalate judgment, not formatting" done properly: this IS judgment, so it is
escalated - but escalated with its evidence attached.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Facts whose value is prose. These are the paragraphs we read FROM; they are
# never the subject OF a statement.
NARRATIVE_FACT_KEYS = (
    "additional_remarks_text", "acord101_remarks", "operations_description",
    "certificate_description_of_operations", "account_description",
    "wc_description_of_operations", "premises_description",
)

# A money amount as a document prints one. Shared with fact_equivalence's
# reader so "$ 3,000,000" and "$3,000,000.00" are the same amount to both.
_AMOUNT_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{1,2})?|\b\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?\b")
_DATE_RE = re.compile(
    r"\b(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2}"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b",
    re.I)

# The verbs that mark an AMENDMENT - a value that changed. Deliberately a closed
# set: "reduced from X to Y" states a new current value, while "ranges from X to
# Y" or "applies from X to Y" do not, and only an explicit change verb can tell
# them apart.
_CHANGE_VERBS = (
    "reduced", "increased", "raised", "lowered", "changed", "amended",
    "revised", "corrected", "restated", "endorsed",
)
_AMENDMENT_RE = re.compile(
    r"\b(?:" + "|".join(_CHANGE_VERBS) + r")\b[^.]{0,40}?\bfrom\b\s*"
    r"(?P<from>" + _AMOUNT_RE.pattern + r")"
    r"\s*\b(?:to|down to|up to)\b\s*"
    r"(?P<to>" + _AMOUNT_RE.pattern + r")",
    re.I)

# "effective 7/25/25", "as of 7/25/25", "with effect from 7/25/25".
_AS_OF_RE = re.compile(
    r"\b(?:effective|as of|with effect from|commencing)\b\s*(?:on\s+)?"
    r"(?P<date>" + _DATE_RE.pattern + r")", re.I)

# A value stated against a label: "a general aggregate of $2,000,000",
# "carries a $1,000 deductible". Bounded so it can only reach inside one clause.
_OF_AMOUNT_RE = re.compile(
    r"\bof\s+(?P<val>" + _AMOUNT_RE.pattern + r")", re.I)

_MIN_LABEL_WORDS = 1
_MAX_SUBJECT_DISTANCE = 60      # chars between the label and its amount


def _sentences(text: str) -> List[str]:
    """Split on sentence enders, keeping each sentence whole.

    A statement never spans a full stop: "The limit was reduced to $1,000,000.
    The premium is $952." must not pair the limit with the premium.
    """
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z0-9\"'])", str(text or ""))
    return [p.strip() for p in parts if p and p.strip()]


# ── Subject vocabulary ───────────────────────────────────────────────────────

def _label_vocabulary(context=None) -> List[tuple]:
    """[(lowercased phrase, fact_key)] - longest phrase first.

    THREE SOURCES, none of them invented here:

    1. ``arq_service._FIELD_PRODUCER_LABEL_MAP`` - 68 curated producer-facing
       labels, already maintained for the questionnaire.
    2. The fact key itself, humanised, plus the ACORD vocabulary already sitting
       in ``fact_registry``'s ``format_hint``-adjacent naming.
    3. **The package's OWN dec-index labels.** If this document printed
       "General Aggregate Limit" against `gl_aggregate`'s amount, that is the
       document teaching us the phrase it uses - better than any table we could
       write, and it arrives already tied to a policy and a line.

    Longest-first ordering matters: "products completed operations aggregate"
    must win over "aggregate".
    """
    vocab: Dict[str, str] = {}

    def _add(phrase: Any, key: str) -> None:
        p = re.sub(r"[^a-z0-9 ]", " ", str(phrase or "").lower())
        p = re.sub(r"\s+", " ", p).strip()
        # A one-word label like "carrier" is too loose to anchor an amount.
        if len(p.split()) >= _MIN_LABEL_WORDS and len(p) >= 4:
            vocab.setdefault(p, key)

    try:
        from services.arq_service import _FIELD_PRODUCER_LABEL_MAP
        for key, label in _FIELD_PRODUCER_LABEL_MAP.items():
            # Producer labels carry a trailing qualifier after " - "; both the
            # full label and its head are legitimate document phrasings.
            _add(label, key)
            _add(str(label).split(" - ")[0], key)
    except Exception:                                        # pragma: no cover
        pass

    try:
        from services.fact_registry import FACT_REGISTRY
        for key in FACT_REGISTRY:
            _add(key.replace("_", " "), key)
            # "gl_aggregate" is printed "general aggregate"; "wc_" as "workers
            # compensation". Expanding the two standing abbreviations is not a
            # per-field list - it is how these prefixes are always written.
            expanded = (key.replace("gl_", "general liability ")
                           .replace("wc_", "workers compensation ")
                           .replace("_", " "))
            _add(expanded, key)
            if key.startswith("gl_"):
                _add("general " + key[3:].replace("_", " "), key)
    except Exception:                                        # pragma: no cover
        pass

    return sorted(vocab.items(), key=lambda kv: -len(kv[0]))


_VOCAB_CACHE: Optional[List[tuple]] = None


def _vocab() -> List[tuple]:
    global _VOCAB_CACHE
    if _VOCAB_CACHE is None:
        _VOCAB_CACHE = _label_vocabulary()
    return _VOCAB_CACHE


def _subject_for(sentence: str, at: int) -> Optional[tuple]:
    """(fact_key, matched phrase) for the label nearest BEFORE position ``at``.

    Nearest-preceding, not "anywhere in the sentence": *"General Liability
    policy BBC7263-26 carries a $1,000 deductible and a general aggregate of
    $2,000,000"* names two subjects, and each amount belongs to the one just
    before it. NO SUBJECT MEANS NO STATEMENT - that is the whole guard against
    the run-B defect, where a bare "effective 07/25/2025" became a policy date.
    """
    low = re.sub(r"[^a-z0-9 ]", " ", sentence.lower())
    best = None
    for phrase, key in _vocab():
        start = 0
        while True:
            i = low.find(phrase, start)
            if i < 0 or i >= at:
                break
            gap = at - (i + len(phrase))
            if (0 <= gap <= _MAX_SUBJECT_DISTANCE
                    and not _clause_break(sentence[i + len(phrase):at])
                    and (best is None or gap < best[0])):
                best = (gap, key, phrase)
            start = i + 1
    return (best[1], best[2]) if best else None


# A coordinating conjunction or a comma ENDS the clause, and therefore ends the
# label's reach. Without this, "...a general aggregate of $2,000,000 and a total
# premium of $6,720" attached the PREMIUM to gl_aggregate, because "total
# premium" is not a phrase in our vocabulary and "general aggregate" was still
# inside the distance window. A label may not reach across "and".
_CLAUSE_BREAK_RE = re.compile(r"\band\b|\bor\b|\bplus\b|[,;:]")


def _clause_break(between: str) -> bool:
    return bool(_CLAUSE_BREAK_RE.search(between))


def _policy_in(sentence: str, context) -> Optional[str]:
    """The contract this sentence is about, when it names a KNOWN one.

    Only contracts the package's own evidence already established - a number we
    have never seen is not turned into a policy reference.
    """
    if context is None or not getattr(context, "contracts", None):
        return None
    flat = re.sub(r"[^a-z0-9]", "", sentence.lower())
    hits = {c for c in context.contracts if c and c in flat}
    if len(hits) != 1:
        return None
    # Return the printing the SENTENCE used, not the normalised match key -
    # "6j7400226" is a comparison key and would read as gibberish on screen.
    # Rebuilt by allowing the document's own separators between the key's
    # characters, so "6J7-40-02---26" and "BBC7263 - 26" both recover.
    key = next(iter(hits))
    printed = re.search(
        "".join(re.escape(ch) + r"[\s.\-]*" for ch in key), sentence, re.I)
    return printed.group(0).strip(" .-") if printed else key


# ── Mining ───────────────────────────────────────────────────────────────────

def mine_statements(text: Any, context=None) -> List[dict]:
    """Statements a narrative paragraph makes, each with its verbatim sentence.

    Never raises: narrative mining is enrichment, and a paragraph we cannot
    parse must degrade to today's behaviour (no statements) rather than break
    the pipeline.
    """
    out: List[dict] = []
    try:
        for sentence in _sentences(text):
            policy = _policy_in(sentence, context)
            as_of_m = _AS_OF_RE.search(sentence)
            as_of = as_of_m.group("date") if as_of_m else None

            # 1. AMENDMENT - the highest-value shape, and the client's own
            #    example. "reduced from $3,000,000 to $1,000,000".
            for m in _AMENDMENT_RE.finditer(sentence):
                subj = _subject_for(sentence, m.start())
                if not subj:
                    continue
                out.append({
                    "kind": "amendment", "subject": subj[0],
                    "matched_label": subj[1],
                    "from": m.group("from").strip(),
                    "to": m.group("to").strip(),
                    "as_of": as_of, "policy_number": policy,
                    "quote": sentence,
                })

            # 2. ATTRIBUTION - "a general aggregate of $2,000,000". Skipped
            #    inside an amendment span, whose amounts are already claimed.
            spans = [(m.start(), m.end()) for m in _AMENDMENT_RE.finditer(sentence)]
            for m in _OF_AMOUNT_RE.finditer(sentence):
                if any(s <= m.start() < e for s, e in spans):
                    continue
                subj = _subject_for(sentence, m.start())
                if not subj:
                    continue
                out.append({
                    "kind": "value", "subject": subj[0],
                    "matched_label": subj[1],
                    "from": None, "to": m.group("val").strip(),
                    "as_of": as_of, "policy_number": policy,
                    "quote": sentence,
                })
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("narrative_facts: mining failed - %s", exc)
    return out


def statements_for_facts(facts: Optional[dict], context=None,
                         docs: Optional[List[dict]] = None) -> List[dict]:
    """Every statement this submission's narrative fields make.

    READS EVERY DOCUMENT, not just the merged facts. Probe run B, 2026-08-17:
    the merge kept one document's short header as `additional_remarks_text` and
    discarded the certificate's paragraph - the one carrying "reduced from
    $3,000,000 to $1,000,000 effective 07/25/2025". Mining the merged value
    alone therefore found nothing and the umbrella card shipped with no
    explanation. Remarks ACCUMULATE (that is the whole reason two paragraphs are
    not rival values), so every copy has to be read.

    Deduped by (subject, from, to, as_of) so one sentence appearing in two
    documents does not read as two separate assertions.
    """
    from services.extraction_service import _fv
    sources = [facts or {}] + [(d.get("facts") or {}) for d in (docs or [])]
    seen, out = set(), []
    for src in sources:
        if not isinstance(src, dict):
            continue
        for key in NARRATIVE_FACT_KEYS:
            val = _fv(src, key)
            if not isinstance(val, str) or not val.strip():
                continue
            for st in mine_statements(val, context):
                sig = (st["subject"], st["from"], st["to"], st["as_of"])
                if sig not in seen:
                    seen.add(sig)
                    st["source_fact"] = key
                    out.append(st)
    return out


# ── The consumer: explain a conflict, never resolve it ───────────────────────

def explain_conflict(fact_key: str, displays: List[str],
                     statements: List[dict]) -> Optional[str]:
    """One sentence the picker can show under a conflict row, or None.

    Requires the statement to actually be ABOUT this conflict: its subject must
    be the field in question AND at least one of the amounts it names must be
    one of the values on the card. A remark that mentions an unrelated figure
    explains nothing and is not shown.

    Returns prose only. It never marks a winner, never pre-selects and never
    writes a fact - the client asked for unresolved to STAY unresolved.
    """
    try:
        from services.fact_equivalence import money_amounts
        on_card = {a for d in displays for a in money_amounts(d)}
        if not on_card:
            return None
        for st in statements or []:
            if st.get("subject") != fact_key:
                continue
            named = set(money_amounts(st.get("from") or "")) | \
                set(money_amounts(st.get("to") or ""))
            if not (named & on_card):
                continue
            if st["kind"] == "amendment":
                when = f" effective {st['as_of']}" if st.get("as_of") else ""
                where = (f" under policy {st['policy_number']}"
                         if st.get("policy_number") else "")
                return (f"The submission's remarks state this was "
                        f"{_verb_in(st['quote'])} from {st['from']} to "
                        f"{st['to']}{when}{where}. Confirm which applies.")
            return (f"The submission's remarks state {st['to']} for this value. "
                    f"Confirm which applies.")
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("narrative_facts: explanation failed for %s - %s",
                       fact_key, exc)
    return None


def _verb_in(quote: str) -> str:
    low = str(quote or "").lower()
    for v in _CHANGE_VERBS:
        if v in low:
            return v
    return "changed"


# ── Honest scope ─────────────────────────────────────────────────────────────
# MINED: amendments ("reduced from X to Y effective D") and labelled values
# ("a general aggregate of $2,000,000"), both anchored to a fact key we already
# own and to a contract the package already evidences.
#
# NOT MINED, and deliberately so - these need language understanding, not a
# lookup, and inventing them from regex would put wrong data on a legal form:
#   * loss/claim rows      "a water damage claim dated 03/14/2023 was paid at
#                           $18,400 and is closed" -> loss_history
#   * exclusions           "excludes any work performed above three stories"
#                           -> operations / underwriting narrative
#   * negative assertions  "the insured confirms no subsidiaries"
# Those remain scoped work; see 17AugIssuesResolving.md.
