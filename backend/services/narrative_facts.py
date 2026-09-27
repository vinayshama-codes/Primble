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
# reader so "$ 3,000,000" and "$3,000,000.00" are the same amount to both. The
# broker's shorthand "$3M" / "$2MM" / "$500K" keeps its multiplier: without it
# "$3M" was read as three dollars (14 Sep break-it pass).
_AMOUNT_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{1,2})?(?:\s?(?:MM|[KMB]|million|mil)\b)?"
                        r"|\b\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?\b"
                        # A bare shorthand amount - "decreased to 1M", "from
                        # 3 million" - keeps its multiplier (24 Sep 2026).
                        r"|\b\d+(?:\.\d+)?\s?(?:MM|[KMB]|million|mil)\b")
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
    "decreased", "cut", "adjusted", "modified",
)
_AMENDMENT_RE = re.compile(
    r"\b(?:" + "|".join(_CHANGE_VERBS) + r")\b[^.]{0,40}?\bfrom\b\s*"
    r"(?P<from>" + _AMOUNT_RE.pattern + r")"
    r"\s*\b(?:to|down to|up to)\b\s*"
    r"(?P<to>" + _AMOUNT_RE.pattern + r")",
    re.I)

# The same change with only its NEW amount named after the verb - "UMBRELLA
# LIMIT CHANGED TO $1M EFFECTIVE 07/25/25", "was reduced to $1,000,000
# effective 7/25/25" - and with only its OLD one, the new amount printed just
# before the verb: "Umbrella $1,000,000 (reduced from $3,000,000 as of
# 7/25/25)". The missing amount is never invented here: `fact_comparison.
# dated_change` supplies it only from the documents' own two printings.
_AMENDMENT_TO_ONLY_RE = re.compile(
    r"\b(?:" + "|".join(_CHANGE_VERBS) + r")\b(?:(?!\bfrom\b)[^.]){0,40}?"
    r"\b(?:to|down to|up to)\b\s*(?P<to>" + _AMOUNT_RE.pattern + r")",
    re.I)
_AMENDMENT_FROM_ONLY_RE = re.compile(
    r"\b(?:" + "|".join(_CHANGE_VERBS) + r")\b[^.]{0,20}?\bfrom\b\s*"
    r"(?P<from>" + _AMOUNT_RE.pattern + r")(?!\s*\b(?:to|down to|up to)\b)",
    re.I)

# "effective 7/25/25", "eff. 7-25-25", "effective date 7/25/25", "as of
# 7/25/25", "with effect from 7/25/25".
_AS_OF_RE = re.compile(
    r"\b(?:effective(?:\s+date)?|eff\.?|as of|as at|with effect from|commencing"
    r"|starting|beginning)(?:\b|(?<=\.))\s*[:\-]?\s*(?:on\s+)?"
    r"(?P<date>" + _DATE_RE.pattern + r")", re.I)

# A value stated against a label: "a general aggregate of $2,000,000",
# "carries a $1,000 deductible". Bounded so it can only reach inside one clause.
_OF_AMOUNT_RE = re.compile(
    r"\bof\s+(?P<val>" + _AMOUNT_RE.pattern + r")", re.I)

_MIN_LABEL_WORDS = 1
_MAX_SUBJECT_DISTANCE = 60      # chars between the label and its amount

# A change verb STATES a change only when the sentence asserts it. "was not
# reduced", "requests the limit be reduced", "will be reduced if approved",
# "can the limit be reduced?" name the same amounts as the Orbin certificate
# and assert nothing - read as a change, each silently settled a real conflict
# and stamped the wrong limit (14 Sep break-it pass). Such a sentence is still
# mined, marked ``asserted: False``: its date remains an endorsement date to
# `extraction_service`, but no rule may treat it as a change that happened.
_NEGATION_RE = re.compile(r"\b(?:not|never|no longer)\b|n['’]t\b", re.I)
_UNREALISED_RE = re.compile(
    r"\b(?:be|will|would|shall|should|may|might|can|could|must)\b", re.I)
_CONDITION_RE = re.compile(r"\b(?:if|unless|whether)\b", re.I)
_ASSERTION_WINDOW_WORDS = 4     # words before the verb, inside its own clause


def _asserts_the_change(sentence: str, verb_at: int) -> bool:
    """False when the change verb at ``verb_at`` is negated, unrealised
    (modal / "be" + participle), conditional, or asked as a question."""
    if str(sentence).rstrip().endswith("?"):
        return False
    head = sentence[:verb_at]
    if _CONDITION_RE.search(head):
        return False
    near = " ".join(re.split(r"[,;:]", head)[-1].split()[-_ASSERTION_WINDOW_WORDS:])
    return not (_NEGATION_RE.search(near) or _UNREALISED_RE.search(near))


def _sentences(text: str) -> List[str]:
    """Split on sentence enders, keeping each sentence whole.

    A statement never spans a full stop: "The limit was reduced to $1,000,000.
    The premium is $952." must not pair the limit with the premium.
    """
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z0-9\"'])", str(text or ""))
    parts = [p.strip() for p in parts if p and p.strip()]
    # An ABBREVIATION's full stop is not a sentence end: "decreased to 1M eff.
    # 7-25-25" was cut before its own date (24 Sep 2026).
    merged: List[str] = []
    for part in parts:
        if merged and _ABBREVIATION_END_RE.search(merged[-1]):
            merged[-1] = merged[-1] + " " + part
        else:
            merged.append(part)
    return merged


_ABBREVIATION_END_RE = re.compile(
    r"\b(?:eff|no|nos|co|inc|ins|approx|appr|incl|excl|ea|per|vs|ltd)\.$", re.I)


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


def _subject_inside(sentence: str, start: int, end: int) -> Optional[tuple]:
    """(fact_key, phrase) for the longest label printed INSIDE ``[start, end)``.

    A change sentence may name its subject AFTER the verb. The Orbin
    certificate prints *"Reduced Umbrella Limit from $3,000,000 to $1,000,000
    Limit Effective 7/25/25"*, and `_subject_for` only looks BEFORE the verb,
    so the client's literal remark produced no statement at all and the
    umbrella card shipped with no explanation - while the test fixture, a
    paraphrase that put the subject first, stayed green (D22). The span is the
    verb-to-"from" gap of ONE amendment match, so the label found there can
    only be the thing that changed.
    """
    low = re.sub(r"[^a-z0-9 ]", " ", sentence.lower())
    for phrase, key in _vocab():                          # longest first
        i = low.find(phrase, start)
        if i >= 0 and i + len(phrase) <= end:
            return key, phrase
    return None


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


# ── OCR glue: a remark printed with its spaces lost (24 Sep 2026) ───────────
# The client's REAL certificate OCR prints its remark as ONE token:
#   Note:ReducedUmbrellaLimitfrom$3,000,000to$1,000,000LimitEffective7/25/25.
# Every pattern in this module reads WORDS, so that sentence produced no
# statement at all - the umbrella stayed a "$3M vs $1M" conflict with no
# explanation. The 14 Sep handoff named this risk "unverified"; a fixture that
# printed the remark with spaces kept every test green (D22).
#
# Re-spaced only where the text is visibly glued (a run of 18+ characters with
# no space), at boundaries the characters themselves mark - a capital after a
# lower-case letter, a "$" after a letter, a digit against a letter, a colon
# before a word - and a lower-case run that is not itself a word is split into
# ACORD's own vocabulary ("Limitfrom" -> "Limit from"), never into anything
# else. Ordinary spaced prose is returned byte-identical.
_GLUED_RUN_RE = re.compile(r"\S{18,}")


def _split_lower_glue(word: str) -> str:
    try:
        from services.field_mapping_integrity import _segment_glued_caps, _acord_vocabulary
        _fields, tips = _acord_vocabulary()
    except Exception:                                        # noqa: BLE001
        return word
    if len(word) < 6 or not word.isalpha() or word.lower() in tips:
        return word
    pieces = _segment_glued_caps(word.lower())
    if not pieces or len(pieces) < 2 or len(pieces) > 3:
        return word
    out, at = [], 0
    for piece in pieces:
        out.append(word[at:at + len(piece)])
        at += len(piece)
    return " ".join(out)


def respace_glued_prose(text: Any) -> str:
    """Undo OCR glue in a remark - see the block comment above."""
    s = str(text or "")
    if not s or not _GLUED_RUN_RE.search(s):
        return s
    out: List[str] = []
    for tok in re.split(r"(\s+)", s):
        if not tok or tok.isspace() or len(tok) < 18:
            out.append(tok)
            continue
        t = re.sub(r"(?<=:)(?=[A-Za-z$])", " ", tok)
        t = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", t)
        t = re.sub(r"(?<=[A-Za-z])(?=\$)", " ", t)
        t = re.sub(r"(?<=\d)(?=[A-Za-z])", " ", t)
        t = re.sub(r"(?<=[a-z])(?=\d)", " ", t)
        out.append(" ".join(_split_lower_glue(w) for w in t.split(" ")))
    return "".join(out)


# A limit-sized amount on a sentence that names the umbrella: the one subject
# we may infer when the vocabulary finds none ("Umbrella decreased to 1M").
_UMBRELLA_WORD_RE = re.compile(r"\b(?:umbrella|excess)\b", re.I)
_LIMIT_SIZED = 100_000


def _umbrella_subject_by_size(sentence: str, amounts: List[Any]) -> Optional[tuple]:
    """("umbrella_limit", word) when the sentence names the umbrella and every
    amount it changes is limit-sized - a premium or a retention never is."""
    m = _UMBRELLA_WORD_RE.search(sentence)
    if not m:
        return None
    try:
        from services.fact_equivalence import money_amounts
        vals = [float(a) for x in amounts if x for a in money_amounts(x)]
    except Exception:                                        # noqa: BLE001
        return None
    if vals and all(v >= _LIMIT_SIZED for v in vals):
        return "umbrella_limit", m.group(0).lower()
    return None



# ── Mining ───────────────────────────────────────────────────────────────────

def mine_statements(text: Any, context=None) -> List[dict]:
    """Statements a narrative paragraph makes, each with its verbatim sentence.

    Never raises: narrative mining is enrichment, and a paragraph we cannot
    parse must degrade to today's behaviour (no statements) rather than break
    the pipeline.
    """
    out: List[dict] = []
    try:
        for sentence in _sentences(respace_glued_prose(text)):
            policy = _policy_in(sentence, context)
            as_of_m = _AS_OF_RE.search(sentence)
            as_of = as_of_m.group("date") if as_of_m else None
            _verbs_done: set = set()

            # 1. AMENDMENT - the highest-value shape, and the client's own
            #    example. "reduced from $3,000,000 to $1,000,000".
            for m in _AMENDMENT_RE.finditer(sentence):
                # The subject may sit between the verb and "from" ("Reduced
                # Umbrella Limit from ...") - the most specific place a subject
                # can be, so it is read first; then the label before the verb.
                subj = (_subject_inside(sentence, m.start(), m.start("from"))
                        or _subject_for(sentence, m.start())
                        or _umbrella_subject_by_size(
                            sentence, [m.group("from"), m.group("to")]))
                _verbs_done.add(m.start())
                if not subj:
                    continue
                out.append({
                    "kind": "amendment", "subject": subj[0],
                    "matched_label": subj[1],
                    "from": m.group("from").strip().rstrip(","),
                    "to": m.group("to").strip().rstrip(","),
                    "as_of": as_of, "policy_number": policy,
                    "quote": sentence,
                    "asserted": _asserts_the_change(sentence, m.start()),
                })

            # 1b. The same change naming only its NEW amount after the verb
            #     ("changed to $1M"), or only its OLD one with the new amount
            #     printed before the verb ("$1,000,000 (reduced from
            #     $3,000,000 ...)"). The missing side stays None here -
            #     `fact_comparison.dated_change` may fill it only from the
            #     documents' own two printings.
            for m in _AMENDMENT_TO_ONLY_RE.finditer(sentence):
                if m.start() in _verbs_done:
                    continue
                subj = (_subject_inside(sentence, m.start(), m.start("to"))
                        or _subject_for(sentence, m.start())
                        or _umbrella_subject_by_size(sentence, [m.group("to")]))
                _verbs_done.add(m.start())
                if not subj:
                    continue
                out.append({
                    "kind": "amendment", "subject": subj[0],
                    "matched_label": subj[1], "from": None,
                    "to": m.group("to").strip().rstrip(","),
                    "as_of": as_of, "policy_number": policy,
                    "quote": sentence,
                    "asserted": _asserts_the_change(sentence, m.start()),
                })
            for m in _AMENDMENT_FROM_ONLY_RE.finditer(sentence):
                if m.start() in _verbs_done:
                    continue
                before = [x for x in _AMOUNT_RE.finditer(sentence[:m.start()])]
                if not before:
                    continue
                new_amt = before[-1]
                # The new amount must sit in the verb's own clause - a
                # parenthesis may separate them, a sentence break may not.
                if re.search(r"[.;]", sentence[new_amt.end():m.start()]):
                    continue
                subj = (_subject_for(sentence, new_amt.start())
                        or _umbrella_subject_by_size(
                            sentence, [new_amt.group(0), m.group("from")]))
                _verbs_done.add(m.start())
                if not subj:
                    continue
                out.append({
                    "kind": "amendment", "subject": subj[0],
                    "matched_label": subj[1],
                    "from": m.group("from").strip().rstrip(","),
                    "to": new_amt.group(0).strip().rstrip(","),
                    "as_of": as_of, "policy_number": policy,
                    "quote": sentence,
                    "asserted": _asserts_the_change(sentence, m.start()),
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
    # DOCUMENTS FIRST, then the merged facts: a statement is credited to the
    # document that prints it (`source_doc_index`), which is what lets the
    # dated-change rule check that the SAME document also states the new value
    # (fact_comparison.dated_change). The merged copy of one document's remark
    # then adds no second, unattributed statement.
    docs = list(docs or [])
    sources = [(i, (d.get("facts") or {}) if isinstance(d, dict) else {})
               for i, d in enumerate(docs)] + [(None, facts or {})]
    seen, out = set(), []
    for doc_index, src in sources:
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
                    st["source_doc_index"] = doc_index
                    out.append(st)
                    continue
                # ONE SENTENCE IN TWO DOCUMENTS (24 Sep 2026): credit the one
                # that PRINTS the new value as the fact itself - the document
                # `dated_change` needs. Crediting whichever came first let a
                # narrative repeating the certificate's note, uploaded before
                # it, turn the dated change back into a conflict.
                if doc_index is None:
                    continue
                prior = next(x for x in out if (x["subject"], x["from"], x["to"],
                                                 x["as_of"]) == sig)
                if _prints_value(src, st["subject"], st["to"]) and not (
                        prior.get("source_doc_index") is not None
                        and _prints_value(sources[prior["source_doc_index"]][1],
                                          st["subject"], st["to"])):
                    prior["source_doc_index"] = doc_index
                    prior["source_fact"] = key
    return out


def _prints_value(facts: Any, subject: Any, amount: Any) -> bool:
    """Does this document state ``amount`` as ``subject`` itself?"""
    try:
        from services.extraction_service import _fv
        from services.fact_equivalence import money_amounts
        own = money_amounts(_fv(facts or {}, subject) or "")
        return bool(own) and bool(set(own) & set(money_amounts(amount or "")))
    except Exception:                                        # noqa: BLE001
        return False


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
            # "was not reduced from X to Y" must never read back as "the
            # remarks state this was reduced from X to Y".
            if st.get("asserted") is False:
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
