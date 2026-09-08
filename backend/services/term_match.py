"""ONE DOOR for "does this text mention this term?".

WHY THIS EXISTS
---------------
Thirty-three places in this codebase asked that question, each with its own
hand-rolled `if term in text`, and a bare substring answers a DIFFERENT question:
"do these letters appear anywhere". Measured live, with controls, 2026-09-06:

    "bank"       inside  2255 SHOREBANK AVENUE      -> buy Crime coverage
    "tech"       inside  HVAC service TECHNICIANS   -> buy Cyber coverage
    "farm"       inside  FARMINGTON HILLS MI        -> vehicle USE = Farm
    "atm"        inside  wastewater TREATMENT plant -> buy Crime coverage
    "coi"        inside  COInsurance_Endorsement.pdf-> classified a certificate
    "California" inside  1450 CALIFORNIA ST, DENVER -> the CALIFORNIA form
    "5403"       inside  payroll 540300             -> a roofing class code

The individual fixes are one-liners. The reason they keep coming back is that
there was no shared door, so each copy rotted on its own - and the proof is that
`sqs_service._lob_from_operations` was fixed on 2026-09-05 while its twin
`_ops_to_industry`, 78 lines below it in the same file, was not.

WHAT THIS IS AND IS NOT
-----------------------
It answers presence, position and ownership. It does NOT know insurance. A term
that is genuinely a whole word in an innocent sentence - "aerial PLATFORM lift",
"occupational HEALTH and safety" - is not a boundary problem and this module
cannot help; those need a longer phrase or a second condition at the call site.
Boundaries fixed 22 of the 33 sites; the rest were recorded, not papered over.

DESIGN RULES
------------
* **Stdlib only, and no `services` / `utils` / `config` import, ever.** This sits
  BELOW every consumer, including `lob_canon`, which is the deepest leaf in the
  service layer. One service import here hands every consumer a cycle, and the
  two consumers that already import each other lazily (`sqs_service` <->
  `cross_form_validator`) could not both import this at module level.
* **Total.** Every public function accepts anything - None, int, bytes, a list of
  dicts, a fact envelope, malformed unicode - and returns a sane empty answer
  rather than raising. These are called from inside score computations, where an
  exception does not surface as a bug report, it surfaces as a missing score
  (see H1-G, the live run that lost its Total Package Score).
* **Opt in to looseness, never inherit it.** `stem` and `plural` default OFF.
  A default `s?` would silently reintroduce a fixed defect: `follow form` must
  NOT match `following forms`, which is the whole of the `_has_explicit_follow_
  form` bug.
* **Fail toward silence.** Ambiguity returns None / False / (), never a guess.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Iterator, Optional, Sequence, Tuple

__all__ = [
    "fold", "fold_term", "present", "matched", "find", "mentions",
    "sole_bucket", "describes_the_subject",
]

# Everything that is not a letter or a digit is a separator. Folding on this and
# padding the result means a whole-word test is `" term " in folded` - no regex
# in the hot path, and "workers' compensation", "E-COMMERCE" and "S.I.C." all
# fold to the same shape as their plain spellings.
_SEPARATORS = re.compile(r"[^a-z0-9]+")

# How deep `fold` will walk a nested structure before giving up. Extraction
# facts nest two levels at most (`risk_transfer.additional_insured_names`); the
# cap exists so a malformed or self-referential value cannot hang a score.
_MAX_DEPTH = 4
_MAX_ITEMS = 500


def _coerce(value: Any, depth: int = 0) -> str:
    """Any value -> the text it carries. Never raises."""
    if value is None or depth > _MAX_DEPTH:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return ""                      # a flag is not text; "True" is not a word
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            return bytes(value).decode("utf-8", "ignore")
        except Exception:              # noqa: BLE001
            return ""
    if isinstance(value, dict):
        # A fact envelope carries its payload under "value"; anything else is a
        # container whose LEAVES are the text (never its repr - the punctuation
        # in `[{'code': ...}]` is exactly how a payroll became a class code).
        if "value" in value:
            return _coerce(value.get("value"), depth + 1)
        return " ".join(_coerce(v, depth + 1) for v in list(value.values())[:_MAX_ITEMS])
    if isinstance(value, (list, tuple, set, frozenset)):
        return " ".join(_coerce(v, depth + 1) for v in list(value)[:_MAX_ITEMS])
    try:
        return str(value)
    except Exception:                  # noqa: BLE001
        return ""


def fold(value: Any) -> str:
    """Text -> a lowercase, space-separated, space-padded comparison string.

    Fold ONCE per haystack and reuse it: the presence helpers take the folded
    string precisely so nobody folds a 700k-character document inside a
    per-term loop.
    """
    try:
        text = _coerce(value)
        if not text:
            return " "
        return " " + _SEPARATORS.sub(" ", text.lower()).strip() + " "
    except Exception:                  # noqa: BLE001
        return " "


@lru_cache(maxsize=4096)
def _fold_term_cached(term: str) -> str:
    return _SEPARATORS.sub(" ", term.lower()).strip()


def fold_term(term: Any) -> str:
    """A term folded to its comparison form, without the padding.

    The cache is keyed on a STRING and the coercion happens outside it: a term
    that arrives as a list or a dict is unhashable, and `lru_cache` raises
    `TypeError` on those before the function body ever runs. Found by feeding
    the door a list - "data can be anything" has to include the term, not just
    the haystack.
    """
    try:
        if not isinstance(term, str):
            term = _coerce(term)
        return _fold_term_cached(term)
    except Exception:                  # noqa: BLE001
        return ""


def _needles(term: str, stem: bool, plural: bool) -> Tuple[str, ...]:
    """The padded forms a match may take, longest first."""
    t = fold_term(term)
    if not t:
        return ()
    if stem:
        # Left boundary only: " agricultur" matches "agricultural" and still
        # cannot match "the agricultur".
        return (" " + t,)
    out = [" " + t + " "]
    if plural:
        out.append(" " + t + "s ")
        if not t.endswith("s"):
            out.append(" " + t + "es ")
    return tuple(out)


def mentions(term: Any, folded: Any, *, stem: bool = False,
             plural: bool = False) -> Iterator[Tuple[int, int]]:
    """Yield (start, end) of every whole-word mention, in order.

    Offsets index the FOLDED string. `describes_the_subject` needs positions,
    not a boolean, because it has to look at what sits either side.
    """
    hay = folded if isinstance(folded, str) else fold(folded)
    for needle in _needles(term, stem, plural):
        if not needle:
            continue
        start = 0
        while True:
            idx = hay.find(needle, start)
            if idx < 0:
                break
            # +1 / -1 strip the padding spaces so the span is the term itself.
            yield (idx + 1, idx + len(needle) - (0 if stem else 1))
            start = idx + 1
        # Only the first matching form is reported, so a plural does not
        # double-count a singular that is also present.
        if hay.find(needle) >= 0:
            return


def find(term: Any, folded: Any, *, stem: bool = False,
         plural: bool = False) -> Optional[int]:
    """Position of the first whole-word mention, or None.

    A position rather than a bool because earliest-keyword-wins is a real rule
    here (`pdf_service._vehicle_use_class` picks the first use named).
    """
    for start, _end in mentions(term, folded, stem=stem, plural=plural):
        return start
    return None


def present(term: Any, folded: Any, *, stem: bool = False,
            plural: bool = False) -> bool:
    return find(term, folded, stem=stem, plural=plural) is not None


def matched(terms: Any, folded: Any, *, stem: bool = False,
            plural: bool = False) -> Tuple[str, ...]:
    """Every term present, de-duplicated, in the order given."""
    if isinstance(terms, (str, bytes)) or not isinstance(terms, Sequence):
        terms = [terms]
    hay = folded if isinstance(folded, str) else fold(folded)
    out, seen = [], set()
    for term in list(terms)[:_MAX_ITEMS]:
        key = fold_term(term)
        if not key or key in seen:
            continue
        seen.add(key)
        if present(key, hay, stem=stem, plural=plural):
            out.append(key)
    return tuple(out)


# ── Ownership: is this term about the SUBJECT, or about its customers? ───────
#
# Moved here from `cross_form_validator`, which wrote it for the identical
# defect one consumer over. It deliberately runs on the RAW (lowercased) text,
# NOT the folded string: the rules key on sentence boundaries, and folding turns
# every full stop into a space, which would let a cue leak across two sentences.
_CUSTOMER_BEFORE_RE = re.compile(
    r"\b(?:to|for|serving|serves|supplying|supplies|sold\s+to|delivered\s+to|"
    r"distribution\s+to|clients?|customers?)\b[^.]{0,40}$", re.I)
_CUSTOMER_AFTER_RE = re.compile(
    r"^[^.]{0,30}?\b(?:accounts?|customers?|clients?|centers?|centres?|"
    r"buildings?|chains?|operators?|owners?|sector|market|markets|industry|"
    r"trade|supply|supplies|distributors?|wholesalers?)\b", re.I)


def describes_the_subject(term: Any, text: Any, *, stem: bool = False,
                          plural: bool = False) -> bool:
    """True when at least one mention of `term` is about the SUBJECT itself.

    "Janitorial services FOR grocery, restaurant and retail accounts" names one
    industry in whole words and means the customers. Word boundaries cannot see
    that, which is why this is a separate layer rather than a stricter matcher.

    Takes the RAW text, not a folded string - see the note on the regexes above.
    """
    try:
        raw = _coerce(text).lower()
        needle = fold_term(term)
        if not raw or not needle:
            return False
        pattern = r"\b" + r"\W+".join(re.escape(p) for p in needle.split())
        if plural:
            pattern += r"(?:e?s)?"
        if not stem:
            pattern += r"\b"
        found = False
        for m in re.finditer(pattern, raw):
            found = True
            if not (_CUSTOMER_BEFORE_RE.search(raw[:m.start()])
                    or _CUSTOMER_AFTER_RE.match(raw[m.end():])):
                return True
        return False if found else False
    except Exception:                  # noqa: BLE001
        return False


def sole_bucket(buckets: Any, text: Any, *, stem: bool = False,
                plural: bool = False, require_subject: bool = False) -> Optional[str]:
    """The ONE bucket this text names, or None.

    `buckets` is ((name, (term, ...)), ...). Two buckets matching means the text
    does not single one out, and the answer is None - never the first one found.
    That rule is what disposes of "restaurant construction contractor", and
    `require_subject` is what disposes of "janitorial services for restaurant
    accounts".

    None is the fail-toward-silence answer: every caller treats it as "no
    verdict", which costs a classification and can never assert a wrong one.
    """
    try:
        raw = _coerce(text)
        if not raw.strip():
            return None
        folded = fold(raw)
        hits = set()
        for entry in list(buckets or ())[:_MAX_ITEMS]:
            try:
                name, terms = entry
            except Exception:          # noqa: BLE001
                continue
            for term in list(terms or ())[:_MAX_ITEMS]:
                if not present(term, folded, stem=stem, plural=plural):
                    continue
                if require_subject and not describes_the_subject(
                        term, raw, stem=stem, plural=plural):
                    continue
                hits.add(name)
                break
        return hits.pop() if len(hits) == 1 else None
    except Exception:                  # noqa: BLE001
        return None
