"""normalization.py

Value Normalization Layer for Conflict Detection (Beta Report §5 / Workstream 2).

Cross-document conflict detection was generating FALSE hard stops and warnings
because equivalent values appearing in different formats were compared as raw
strings. Examples from Beta Test 2 (Orbin Contracting):

    ORBIN CONTRACTING LLC   vs  Orbin Contracting, LLC      (name formatting)
    07/15/25                vs  7/15/2025                   (date formatting)
    LLC                     vs  Limited Liability Company   (entity synonym)
    4800 DAHLIA ST #D13     vs  4800 Dahlia Street D13       (address formatting)
    CSL                     vs  Combined Single Limit       (insurance synonym)
    Employers Mutual ...    vs  EMC Property & Casualty ...  (carrier alias)

This module provides the normalization primitives + a single dispatcher so the
cross-document conflict detectors compare NORMALIZED values, while the callers
keep the RAW values for display. A conflict is generated only when the
normalized values *materially* differ.

Design notes
------------
* PURE module — no DB, no I/O, no network. Easy to unit-test. Mirrors
  ``submission_integrity.py`` and ``underwriting_consistency.py``.
* Normalization is COMPARISON-ONLY. It never mutates stored facts. Raw values
  remain the source of truth for display (Beta Report §5.1: "Preserve raw
  values for user display").
* CARRIER aliases are handled as a *seed map + review* (per product decision):
  a small curated carrier-family map collapses known aliases (EMC ↔ Employers
  Mutual Casualty); any UNMATCHED carrier difference is surfaced for REVIEW
  rather than as a definitive hard conflict (Beta Report §5.2 carrier handling).
"""

import re
from datetime import datetime
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

NORMALIZATION_MODEL_VERSION = "1.0.0"


# ── Field categorization (which normalizer applies to which fact key) ─────────

NAME_FIELDS = frozenset({
    "applicant_name", "dba_name", "named_insured", "insured_name",
    "business_name", "loss_run_insured_name",
})
DATE_FIELDS = frozenset({
    "effective_date", "expiration_date",
    "policy_effective_date", "policy_expiration_date",
})
ENTITY_TYPE_FIELDS = frozenset({
    "entity_type", "legal_entity_type", "business_type", "organization_type",
})
ADDRESS_FIELDS = frozenset({
    "mailing_address", "physical_address", "premises_address",
    "location_address", "insured_address",
})
CARRIER_FIELDS = frozenset({
    "carrier_name", "prior_carrier", "carrier", "current_carrier", "insurer_name",
    "wc_prior_carrier",
})
FEIN_FIELDS = frozenset({"fein", "fein_ssn", "tax_id"})
# `valuation_method` is normalized to "RCV"/"ACV" (the industry 3-letter term)
# at extraction time, but the real ACORD 140/141 ValuationCode field's own
# tooltip documents a SINGLE-LETTER code (A/R/V/M) - pdf_service now
# translates to that code when it stamps the field deterministically. Without
# a dedicated normalizer here, field_qa's value-vs-source check compared the
# stamped "R" against the untranslated fact "RCV" and flagged a false
# mismatch (confirmed live 2026-07-17) - a SEPARATE bug from the "RCV" vs "R"
# display inconsistency that prompted the stamping fix in the first place.
# Deliberately its OWN explicit field set rather than added to the generic
# _GENERAL_SYNONYMS table: "R"/"A" are single letters that would collide with
# unrelated fields' legitimate values (a grade, a class code, an initial) if
# expanded as a context-free global synonym.
VALUATION_METHOD_FIELDS = frozenset({"valuation_method"})

# Curated name-like keys that hold an organization name but do NOT end in
# "_name" (holder / payee style). Extend here if new such keys appear.
_NAME_LIKE_KEYS = frozenset({"certificate_holder"})


# ── Yes / No: ONE vocabulary and ONE type door (SYS-07, 2026-09-04) ───────────
#
# The client's item: *"The same affirmative answer can arrive as 'Yes,' boolean
# true, X, or a checked box depending on the source document and extraction
# path. These representation differences should not create false conflicts...
# Route this through the same pre-comparison canonicalization layer used for
# other equivalent values."* This module IS that layer, so the vocabulary lives
# here and every other module asks it.
#
# WHY IT LIVES HERE AND NOT IN THE COMPARATOR. Before this, EIGHT modules each
# carried a private "what counts as affirmative" list and no two agreed:
# `fact_equivalence._YES` knew "x", `pdf_service._resolve_bool_indicator` did
# not (so an affirmative X on a certificate ticked the *No* box on a generated
# ACORD form), `answer_semantics._AFFIRM_TOKENS` knew neither "x" nor "1", and
# NONE of them knew a checkmark glyph. Same one-rule-many-copies shape as C1's
# five comparison sites and H1-C's phantom keys. `normalization` is the leaf
# every one of those modules can already import, so it is the only place the
# rule can sit without a new dependency edge.
#
# WHAT IT REFUSES TO DECIDE, deliberately:
#   * "N/A" / "not applicable" - a NON-ANSWER, not a No. `answer_semantics`
#     owns that distinction (C2-G) and core principle 3 forbids turning an
#     absence into a negative.
#   * a bare ballot-X glyph with no box around it (U+2717 / U+2718) - it means
#     "checked" in a column and "wrong/no" standing alone. No opinion.
#   * anything that is not the WHOLE value. "Yes - see attached schedule" is
#     not a bare token, so it falls through to ordinary text comparison rather
#     than being read as a bald Yes.
# In every one of those cases the answer is None ("cannot say"), which callers
# must treat as "compare it as text", never as a No.

_YES_TOKENS = frozenset({
    "y", "yes", "true", "t", "1", "on", "checked",
    "x",                  # the mark a broker puts in an ACORD checkbox
    "✓", "✔",     # ✓ ✔  check marks
    "☑", "☒",     # ☑ ☒  ballot box CHECKED (either mark inside the box)
    "included", "include",
    # A DECLARATIONS PAGE DOES NOT SAY "Yes". It says the coverage is there.
    # Live-shape vocabulary, whole-value only: a grid cell reading "Covered" is
    # the same affirmative as the certificate's "X" for the same coverage.
    # "applicable" is deliberately ABSENT - "Not Applicable" must stay a
    # NON-answer (core principle 3), and the negation rule below would turn it
    # into a No the moment "applicable" became an affirmative.
    "covered", "elected", "purchased", "applies", "provided", "afforded",
    "carried", "granted",
})
_NO_TOKENS = frozenset({
    "n", "no", "false", "f", "0", "off", "unchecked",
    "☐",               # ☐  ballot box EMPTY
    "excluded", "exclude",
    "declined", "decline", "rejected", "waived",
})
# Read AFTER a negation only: "no coverage" is a No, a box reading "coverage"
# on its own asserts nothing.
_YN_NEGATABLE_NOUNS = frozenset({"coverage", "cover", "coverages"})
# NEGATION IS STRUCTURAL, NOT ENUMERATED. "not covered" / "not purchased" /
# "no coverage" are one rule, not three table rows - so an affirmative added
# above is negatable the day it is added and cannot be half-covered.
_YN_NEGATION_RE = re.compile(r"^(?:not|no|non)[\s-]+(?P<rest>.+)$")
# OCR letter-spacing on a scanned form: "Y e s", "N o". Only when the WHOLE
# value is single letters - "A B C" joins to "abc" and is still not a token.
_YN_SPACED_LETTERS_RE = re.compile(r"^(?:[A-Za-z][ ]){1,5}[A-Za-z]$")
# NOT in either table, on purpose: "none", "null", "blank", "n/a". Those are
# the machine's own spellings of "no value found" and a human's non-answer -
# `_fv`, `underwriting_consistency._normalize` and `answer_semantics` already
# own them, and reading one as a No would turn an absence into a negative
# (core principle 3). "check" is out too: on its own it is as likely a payment
# method as a tick.
# The subset that is unambiguous ENGLISH rather than a mark. Only these license
# the value-shaped fallback in `fact_equivalence.same_fact`: a bare "1" against
# a bare "0" on an untyped field must stay two numbers, not become Yes vs No.
_YES_NO_STRONG_WORDS = frozenset({
    "yes", "no", "true", "false", "checked", "unchecked",
})
# One layer of brackets/parens a checkbox is often transcribed inside: "[X]",
# "(x)", "{X}". An EMPTY pair strips to nothing and yields no opinion - an
# empty bracket is far more often OCR noise than an asserted negative.
_YN_BRACKET_RE = re.compile(r"^[\[\(\{<]\s*(.*?)\s*[\]\)\}>]$")
# Brackets are trimmed as well as matched by `_YN_BRACKET_RE`: OCR routinely
# drops one half of a checkbox pair, leaving "X]" or "[X".
_YN_TRIM_CHARS = " \t\r\n.,;:!*_'\"`[]()<>{}"


def yes_no_token(value: Any) -> Optional[str]:
    """``"Y"`` / ``"N"`` / ``None`` for one value. THE affirmative reader.

    ``None`` means "this is not a Yes/No answer" - never "No". A real ``bool``
    is answered directly: the previous implementation did ``str(value or "")``,
    so ``False`` collapsed to the empty string and a stored boolean *False*
    was silently unreadable.
    """
    if isinstance(value, bool):
        return "Y" if value else "N"
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    # PDF checkbox export values print as /Yes, /On, /1.
    s = s.lstrip("/").strip()
    m = _YN_BRACKET_RE.match(s)
    if m:
        s = m.group(1).strip()
    s = s.strip(_YN_TRIM_CHARS)
    if not s:
        return None
    if _YN_SPACED_LETTERS_RE.match(s):
        s = s.replace(" ", "")
    if s in _YES_TOKENS:
        return "Y"
    if s in _NO_TOKENS:
        return "N"
    neg = _YN_NEGATION_RE.match(s)
    if neg:
        rest = neg.group("rest").strip(_YN_TRIM_CHARS)
        if rest in _YES_TOKENS or rest in _YN_NEGATABLE_NOUNS:
            return "N"
    return None


# A value that arrives carrying its OWN question: "Hired and Non-Owned Auto
# Coverage: X". Live run 1 (2026-09-04): the extractor returned the whole
# printed line for the certificate and a bare "X" for the same layout in
# another package, so one document's answer conflicted with the other's purely
# because of where the model chose to stop reading. That is SYS-07's own class -
# the client's wording is "depending on the source document AND EXTRACTION PATH".
#
# A LABEL IS NOT A QUALIFIER, and that distinction is the whole safety argument:
#   "Hired and Non-Owned Auto Coverage: X"  -> the label restates the question,
#                                              the answer is X
#   "Yes - see the attached schedule"       -> the tail QUALIFIES the answer and
#                                              must never be flattened
# The tail therefore has to be a WHOLE bare token, which the second shape fails.
# SEPARATORS: EVERY way a printed form divides a question from its answer.
#
# The first cut accepted ":" and "=" only, because that is what the live run
# happened to print - which is fitting the fixture, the exact thing the change
# quality bar forbids. A dec page, a broker worksheet and a scanned grid divide
# the two with a dash, a column gap, a dot leader or a table pipe just as often:
#
#     Hired and Non-Owned Auto Coverage: X          colon
#     Hired and Non-Owned Auto Coverage = X         equals
#     Hired and Non-Owned Auto Coverage - X         hyphen / en / em dash
#     Hired and Non-Owned Auto Coverage .......  X  dot leader
#     Hired and Non-Owned Auto Coverage    X        a COLUMN GAP, which is what
#                                                   a two-column layout becomes
#                                                   once it is flattened to text
#     Hired and Non-Owned Auto Coverage | X         a table cell boundary
#
# WIDENING THE SEPARATORS IS SAFE BECAUSE THE TAIL TEST DOES THE WORK, not the
# separator. A qualifier is never a bare Yes/No token:
#     "Yes - see the attached schedule"   tail = "see the attached schedule"  no
#     "Yes, but only for scheduled autos" tail is not reached (no separator)   no
#     "Yes - only scheduled autos"        tail = "only scheduled autos"        no
# The dash was originally excluded for fear of the first of those. That fear was
# unfounded - it fails on the tail, not on the separator - and excluding the
# dash cost real coverage.
_YN_LABEL_SPLIT_RE = re.compile(
    r"^(?P<head>.*\S)"                      # greedy: find the LAST separator
    r"[ \t]*(?::|=|\||\t|—|–|-|\.{2,}|[ ]{1,})[ \t]*"
    r"(?P<tail>\S{1,24})$"
)
# Every character the separator alternation can consume, so a head can never
# retain one. Kept beside the pattern it mirrors.
_YN_SEP_CHARS = " 	:=|.—–-"
_YN_LABEL_MAX_WORDS = 12          # a question label, never a paragraph
_YN_LABEL_MAX_CHARS = 140
# A LABEL IS MADE OF WORDS. The structural guard that stops a numeric pair from
# being read as an answer: "3 - 0" has no label, so its "0" is a score and not a
# No. Requires one real alphabetic word, which every genuine question label has
# and no ratio, score, time or measurement does.
_YN_LABEL_WORD_RE = re.compile(r"[A-Za-z]{3,}")
# A label that is ITSELF a non-answer cannot license reading the mark beside
# it: "N/A: X" says the question does not apply, whatever the X is. The same
# spellings `_fv` and `underwriting_consistency._normalize` already drop.
_YN_LABEL_NON_ANSWERS = frozenset({
    "n/a", "na", "n a", "not applicable", "none", "null", "unknown", "tbd",
})


def yes_no_answer(value: Any) -> Optional[str]:
    """``"Y"`` / ``"N"`` / ``None``, reading a LABELLED answer as well as a bare
    one. Use this wherever the FIELD is already known to hold a Yes/No.

    ``yes_no_token`` stays strict on purpose: it is what licenses the
    value-shaped fallback in ``fact_equivalence``, which runs on facts nothing
    declares, and a labelled value there would be read on no evidence at all.
    """
    tok = yes_no_token(value)
    if tok:
        return tok
    if value is None or isinstance(value, bool):
        return None
    # A LINE BREAK IS A COLUMN BOUNDARY. Joining with a single space made
    # a two-line table cell - one of the commonest flattened shapes there
    # is - indistinguishable from prose. Two spaces keep it a separator.
    s = "  ".join(str(value).split("\n")).strip()
    if not s or len(s) > _YN_LABEL_MAX_CHARS:
        return None
    m = _YN_LABEL_SPLIT_RE.match(s)
    if not m:
        return None
    head, tail = m.group("head").strip(), m.group("tail").strip()
    # THE HEAD MUST NOT KEEP A SEPARATOR. Once a single space counts as a
    # divider the greedy head absorbs the real separator - "Not Applicable - X"
    # splits to head "Not Applicable -", which is not the string the non-answer
    # table holds, so the label escaped every check below and the X was read as
    # a Yes on a question that does not apply. Strip them and the checks see the
    # actual label.
    head = head.rstrip(_YN_SEP_CHARS).strip()
    if not head:
        return None
    # THE TAIL CARRIES THE ANSWER, and it has to be a WHOLE bare token. This is
    # the condition that keeps every qualifier out, whatever divides it.
    tail_tok = yes_no_token(tail)
    if not tail_tok:
        return None
    # A BARE DIGIT AFTER A LABEL IS A NUMBER, NOT AN ANSWER. "0"/"1" alone on a
    # Yes/No field can only be the answer - there is nothing else the box holds.
    # Behind a label they are exactly the shape of a labelled COUNT or amount,
    # and "Total Losses - 0" is not a No. Found by the fuzz sweep, not by
    # reasoning: the first cut read it as one.
    if tail.strip(_YN_TRIM_CHARS).isdigit():
        return None
    # The head must read as a LABEL: short, made of words, not a paragraph, and
    # not itself a non-answer.
    if len(head.split()) > _YN_LABEL_MAX_WORDS or ". " in head:
        return None
    if not _YN_LABEL_WORD_RE.search(head):
        return None
    if head.strip(_YN_TRIM_CHARS).lower() in _YN_LABEL_NON_ANSWERS:
        return None
    # A NEGATION IMMEDIATELY BEFORE THE TAIL BELONGS TO THE TAIL. Widening the
    # separator to a single space put "Hired Auto Not Covered" within reach of
    # the splitter, where the head would end "Not" and the tail read as a Yes -
    # the exact inversion this whole item exists to prevent. Refuse; ordinary
    # text comparison then applies and nobody guesses.
    if head.split()[-1].strip(_YN_TRIM_CHARS).lower() in ("not", "no", "non", "never"):
        return None
    # If the label is ITSELF a Yes/No answer, the two must agree. A value that
    # says both things says neither.
    head_tok = yes_no_token(head)
    if head_tok and head_tok != tail_tok:
        return None
    return tail_tok


def canonical_yes_no(value: Any) -> Optional[str]:
    """The ONE canonical printing of an affirmative / negative, or None.

    This is the "one canonical true value / one canonical false value" the
    acceptance criteria asks for. Callers that need ACORD's single-letter form
    take ``yes_no_answer`` / ``yes_no_token`` instead - same vocabulary,
    different printing.
    """
    tok = yes_no_answer(value)
    return {"Y": "Yes", "N": "No"}.get(tok) if tok else None



# ── A POLICY NUMBER FIELD, AND A VALUE CARRYING ITS OWN LABEL ───────────────
# Both derived, both owned here, for the same reason the Yes/No vocabulary is:
# `fact_comparison`, `fact_equivalence` and `pdf_service` all need the same
# answer and a second copy is how the auto-symbol and Umbrella-SIR bugs each
# survived their first fix.
_POLICY_NUM_WORDS = ("number", "num", "no", "nbr", "id")


def is_policy_number_field(fact_key: Any) -> bool:
    """True when this fact names a POLICY CONTRACT number.

    Derived from the key's own tokens, never a list: `policy_number`,
    `prior_policy_number`, `umbrella_policy_number` and the per-coverage-line
    form `policy_number@auto` all answer True the day they are added.
    A `certificate_number` does NOT - a certificate is not the contract.
    """
    k = str(fact_key or "").split("@", 1)[0].lower()
    toks = [t for t in re.split(r"[^a-z0-9]+", k) if t]
    return "policy" in toks and any(w in toks for w in _POLICY_NUM_WORDS)


# A value that arrives carrying its own printed label - the SYS-07 shape, one
# fact over. Live run 1 showed the extractor returning the whole printed line
# for one document and the bare value for the same layout in another, so one
# document's answer conflicted with the other's purely by where the model
# stopped reading. The label must END in a separator or a number-word, so a
# value that merely BEGINS with one of these words is untouched.
_LEADING_LABEL_RE = re.compile(
    r"^(?:policy|certificate|cert|binder|contract|pol)\s*"
    r"(?:no\.?|number|num|nbr|#)?\s*[:#\-]?\s+(?P<rest>\S.*)$",
    re.IGNORECASE)


def strip_leading_label(value: Any) -> str:
    """``"Policy No. BBC7263"`` -> ``"BBC7263"``. Unchanged when there is no
    label, so it is always safe to call."""
    s = str(value or "").strip()
    m = _LEADING_LABEL_RE.match(s)
    return m.group("rest").strip() if m else s


def is_strong_yes_no_word(value: Any) -> bool:
    """True when the value is an unambiguous English boolean word.

    The STRUCTURAL second condition (H1-F's standing lesson: a test that is
    necessary but not sufficient needs one). "X" is a Yes only when something
    unambiguous sits opposite it.
    """
    if isinstance(value, bool):
        return True
    s = str(value or "").strip().lower().lstrip("/").strip()
    m = _YN_BRACKET_RE.match(s)
    if m:
        s = m.group(1).strip()
    return s.strip(_YN_TRIM_CHARS) in _YES_NO_STRONG_WORDS


# ── Which FIELDS hold a Yes/No ───────────────────────────────────────────────
# Curated overrides only. Everything else is DERIVED from declarations that
# already exist, so a Yes/No fact added tomorrow is classified correctly the
# day it is added and nobody has to remember this list.
YES_NO_FIELDS: FrozenSet[str] = frozenset()

_YES_NO_SHAPE_TOKENS = frozenset({"indicator", "required", "confirmed"})
_YES_NO_SHAPE_PREFIXES = ("is_", "has_")
_YES_NO_SHAPE_SUFFIXES = ("_yn", "_y_n")
# A key that NAMES another type is not a Yes/No however it starts. `has_` and
# `is_` are a guess, and a guess must never outrank a key that says outright it
# holds an amount, a count or a date - `has_umbrella` is a boolean,
# `has_umbrella_limit` would not be. Declared Yes/No facts are unaffected: this
# only ever gates `yes_no_field_shape`, which is the weakest of the sources.
_YES_NO_SHAPE_BLOCKERS = frozenset({
    "amount", "limit", "limits", "value", "values", "premium", "cost", "costs",
    "payroll", "revenue", "sales", "deductible", "deductibles", "sir",
    "count", "number", "num", "employees", "vehicles", "locations", "years",
    "year", "date", "dates", "code", "codes", "rate", "rates", "percent",
    "pct", "phone", "email", "address", "name", "naic", "fein", "id",
})

# Probes for the FACT_REGISTRY validator. A field is Yes/No when its own
# declared validator accepts both booleans and rejects every other shape a
# fact can hold - a BEHAVIOURAL test, so it needs no source parsing and cannot
# drift from what the validator actually does.
_YN_PROBE_ACCEPT = ("Yes", "No")
_YN_PROBE_REJECT = ("$1,000,000", "Acme Contracting LLC", "12/31/2026",
                    "84-2210987", "4800 Dahlia St Denver CO 80216", "238160")

_YES_NO_FIELD_CACHE: Dict[str, bool] = {}
_BOOLEAN_SCHEMA_KEYS: Optional[FrozenSet[str]] = None


def _boolean_schema_keys() -> FrozenSet[str]:
    """Fact keys LLM call 1's own schema declares as ``boolean``.

    Lazy + cached + fail-open: ``extraction_service`` imports this module, so
    the edge only ever exists at call time. Same pattern ``fact_equivalence``
    already uses to read ``FACT_REGISTRY``.
    """
    global _BOOLEAN_SCHEMA_KEYS
    if _BOOLEAN_SCHEMA_KEYS is None:
        try:
            from services.extraction_service import BOOLEAN_FACT_KEYS
            _BOOLEAN_SCHEMA_KEYS = frozenset(BOOLEAN_FACT_KEYS)
        except Exception:                                    # pragma: no cover
            return frozenset()
    return _BOOLEAN_SCHEMA_KEYS


def _registry_declares_yes_no(field: str) -> bool:
    try:
        from services.fact_registry import FACT_REGISTRY
        entry = FACT_REGISTRY.get(field) or {}
    except Exception:                                        # pragma: no cover
        return False
    hint = str(entry.get("format_hint") or "").strip().lower()
    if hint.startswith("yes or no") or hint in ("yes/no", "y/n"):
        return True
    validate = entry.get("validate")
    if not callable(validate):
        return False
    try:
        if not all(bool(validate(p)) for p in _YN_PROBE_ACCEPT):
            return False
        if any(bool(validate(p)) for p in _YN_PROBE_REJECT):
            return False
    except Exception:
        return False
    return True


def declares_yes_no(field: str) -> bool:
    """AUTHORITATIVE: this fact is declared Yes/No somewhere it already was."""
    f = (field or "").strip()
    if not f:
        return False
    return (f in YES_NO_FIELDS
            or f in _boolean_schema_keys()
            or _registry_declares_yes_no(f))


def yes_no_field_shape(field: str) -> bool:
    """A GUESS from the key's own shape - weaker than ``declares_yes_no``."""
    f = (field or "").strip().lower()
    if not f:
        return False
    toks = set(re.split(r"[^a-z0-9]+", f))
    if toks & _YES_NO_SHAPE_BLOCKERS:
        return False
    if toks & _YES_NO_SHAPE_TOKENS:
        return True
    return f.startswith(_YES_NO_SHAPE_PREFIXES) or f.endswith(_YES_NO_SHAPE_SUFFIXES)


def is_yes_no_field(field: str) -> bool:
    """True when this fact holds a Yes/No answer. Declared first, shape second.

    Cached: called inside grouping loops by both the merge and the comparator.
    """
    f = (field or "").strip()
    if not f:
        return False
    hit = _YES_NO_FIELD_CACHE.get(f)
    if hit is None:
        hit = declares_yes_no(f) or yes_no_field_shape(f)
        _YES_NO_FIELD_CACHE[f] = hit
    return hit


# ── A RATING BUREAU IS NEVER THE CARRIER (2026-09-05) ────────────────────────
# The client's own SYS-07 screenshot offers three carriers to choose between:
# EMPLOYERS MUTUAL CASUALTY COMPANY / **AAIS** / EMC Property & Casualty
# Company. AAIS is the American Association of Insurance Services - an advisory
# and rating BUREAU. Its name is printed on the policy because it wrote the
# coverage FORMS ("AAIS Form CL-100"), never because it wrote the policy.
#
# Measured before the fix: `compare("carrier_name", [EMC..., "AAIS"])` returned
# a conflict, `normalize_carrier("AAIS")` returned a carrier family token, and a
# grep of the whole backend found AAIS mentioned ONLY inside the ISO/AAIS
# FORM-NUMBER convention. Nothing anywhere said a bureau is not an insurer. A
# producer who picked it would have stamped "AAIS" as the carrier on a signed
# ACORD form.
#
# This is a DECLARATION, not a heuristic - the same kind of curated table as
# `_STRICT_TOKEN_CANON` - because there is no derivable signal that separates
# "American Association of Insurance Services" from a real insurer's name.
# It is deliberately tiny and holds only bodies that publish forms, rates or
# standards and write no insurance at all.
_INSURANCE_BUREAUS: FrozenSet[str] = frozenset({
    "aais",                                  # American Association of Ins. Services
    "american association of insurance services",
    "iso", "insurance services office", "iso properties", "verisk",
    "ncci", "national council on compensation insurance",
    "naic", "national association of insurance commissioners",
    "acord",                                 # publishes the forms themselves
    "aaisonline",
    "wcirb", "wcribma", "ncrb", "ncci holdings",
    "surplus lines association", "aaisdirect",
})


# ── A ROLE LABEL IS NOT A NAME (2026-09-05) ──────────────────────────────────
# Live 5 Sep 2026: all three generated forms carried an ADDITIONAL INTEREST
# whose NAME was the words "Certificate Holder". The certificate's remarks say
# *"Certificate holder is an additional insured with respect to general
# liability where required by written contract"* - a sentence about the ROLE,
# naming nobody - and the extractor returned the label as the value.
#
# The orphan-row rule already suppresses an UNNAMED interest row. This row had
# a name, so it survived; the name was just not a name. These are ACORD's own
# party-role words, and no company is called one of them.
_PARTY_ROLE_LABELS: FrozenSet[str] = frozenset({
    "certificate holder", "certificate holders", "cert holder",
    "additional insured", "additional insureds", "additional interest",
    "named insured", "first named insured", "other named insured",
    "loss payee", "lender", "lenders loss payable", "lienholder",
    "mortgagee", "mortgage holder", "trustee", "registrant", "owner",
    "employee as lessor", "breach of warranty", "co owner", "co-owner",
    "insured", "applicant", "producer", "agency", "carrier", "insurer",
    "as their interests may appear", "atima", "various", "as required",
    "as per written contract", "where required by written contract",
    "to whom it may concern", "n a", "same as above", "see attached",
})


def is_party_role_label(value: Any) -> bool:
    """True when this "name" is an ACORD party ROLE rather than a party.

    A generic role word is what a document prints when it is describing the
    arrangement instead of naming anybody, so on a name field it carries no
    signal at all.
    """
    s = str(value or "").strip().lower()
    if not s:
        return False
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s in _PARTY_ROLE_LABELS


# ── WHAT THE BUSINESS IS: ONE CLASSIFICATION DOOR (2026-09-05) ───────────────
# NAICS sector -> the kind of business it names. An official published taxonomy,
# not a keyword list. Deliberately PARTIAL: sectors whose reading is genuinely
# arguable (54 Professional Services is "office" or "service" depending on who
# you ask; 53 Real Estate is not "apartments") are absent, and absent means the
# caller falls back to whatever weaker signal it has.
#
# Lives here rather than in `pdf_service` because TWO consumers now need it and
# they must not each keep a copy: the ACORD 125 NATURE OF BUSINESS boxes, and
# `cross_form_validator`'s crime-exposure advisory - which was reading the same
# narrative with the same bare substring test and firing "the business mentions
# 'retail'" at a food wholesaler.
_NAICS_SECTOR_TO_BUSINESS_TYPE: Dict[str, str] = {
    "31": "Manufacturing", "32": "Manufacturing", "33": "Manufacturing",
    "42": "Wholesale",
    "44": "Retail", "45": "Retail",
    "61": "Institutional", "62": "Institutional",
    "23": "Contractor",
}
_NAICS_SUBSECTOR_TO_BUSINESS_TYPE: Dict[str, str] = {
    "722": "Restaurant",          # Food Services and Drinking Places
    "52": "Financial",            # Finance and Insurance
}


def naics_business_type(naics_code: Any) -> Optional[str]:
    """The kind of business this NAICS code names, or None if it cannot say."""
    raw = re.sub(r"\D", "", str(naics_code or ""))
    if len(raw) < 2:
        return None
    return (_NAICS_SUBSECTOR_TO_BUSINESS_TYPE.get(raw[:3])
            or _NAICS_SUBSECTOR_TO_BUSINESS_TYPE.get(raw[:2])
            or _NAICS_SECTOR_TO_BUSINESS_TYPE.get(raw[:2]))


def is_insurance_bureau(value: Any) -> bool:
    """True when this name is a rating / advisory bureau rather than an insurer.

    A bureau's name reaches a carrier fact because it is printed on the policy
    as the author of the coverage FORMS. It is never the party on the risk, so
    on a carrier field it is not a value at all.
    """
    s = str(value or "").strip().lower()
    if not s:
        return False
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if s in _INSURANCE_BUREAUS:
        return True
    # "AAIS Form CL-100", "ISO Commercial Lines" - the bureau named as the
    # AUTHOR of something. Only ever the LEADING token, so "Verisk Insurance
    # Company" (were one to exist) is untouched by a trailing match.
    head = s.split(" ")[0]
    if head in _INSURANCE_BUREAUS and len(s.split()) <= 4:
        return True
    return False


def _infer_field_category(field: str) -> Optional[str]:
    """Infer a normalization category from the SHAPE of a fact key.

    The explicit *_FIELDS sets are the authoritative overrides; this is the
    fallback so any SECONDARY or NEW key carrying a known data type still gets
    type-correct normalization instead of silently dropping to the generic text
    normalizer (Beta Report §5: normalization must be generic for any document,
    not only the canonical identity fields). Returns one of
    {"date", "address", "carrier", "name"} or None.
    """
    if not field:
        return None
    f = field.lower()
    # Date: any "..._date" key (effective / expiration / retro / completion / ...).
    if f.endswith("_date"):
        return "date"
    # Address: any "..._address" / "..._addresses" key.
    if f.endswith("_address") or f.endswith("_addresses"):
        return "address"
    # Carrier: any key naming a carrier/insurer - but NOT a NAIC code, a coverage
    # "type", or a generic "_code" (those are not carrier NAMES).
    if ("carrier" in f or "insurer" in f) and "naic" not in f \
            and not f.endswith("_type") and not f.endswith("_code"):
        return "carrier"
    # Organization name: any "..._name" key, plus curated holder/payee keys.
    if f.endswith("_name") or f in _NAME_LIKE_KEYS:
        return "name"
    return None


def is_carrier_field(field: str) -> bool:
    """True when ``field`` names a carrier/insurer.

    Mirrors the carrier dispatch in normalize_value (explicit set OR inferred
    shape) so the cross-document detector labels carrier differences - including
    secondary keys like wc_prior_carrier - as a REVIEW item rather than a
    definitive conflict (Beta Report §5.2).
    """
    return field in CARRIER_FIELDS or _infer_field_category(field) == "carrier"


# ── Entity suffixes / synonyms ────────────────────────────────────────────────

# Trailing entity-type suffixes stripped from organization NAMES so the name
# identity ("orbin contracting") is compared without the legal suffix.
_ENTITY_SUFFIXES = (
    "limited liability company", "limited liability partnership",
    "limited partnership", "incorporated", "corporation", "company", "limited",
    "llc", "inc", "corp", "co", "ltd", "llp", "lp", "pllc", "pc", "pa", "dba",
)

# Entity-type SYNONYMS (Beta Report §5.2). Each variant maps to a canonical
# token so "LLC" and "Limited Liability Company" compare equal. Sorted longest
# phrase first at module load so multi-word phrases are matched before the
# single words they contain.
_ENTITY_TYPE_SYNONYMS = {
    "limited liability company": "llc",
    # ── V1 H4 (client section 9), 2026-08-27 ────────────────────────────────
    # Section 9.1's Entity Type key rule is *"Normalize equivalent legal
    # formats"*, and it was failing on ACORD'S OWN WORDING. Measured before
    # this line existed:
    #     values_conflict("entity_type", ["LLC", "Limited Liability Corporation"])
    #         -> True
    # because the full phrase was not a key here, so the longest-first pass
    # matched the bare words instead: "limited" -> "ltd" and "corporation" ->
    # "corp", giving "ltd liability corp". ACORD 125's own checkbox is labelled
    # "Limited Liability Corporation", so the single most likely spelling on a
    # real form raised a false Data Consistency conflict against "LLC" - and
    # `entity_type` IS a reconcilable field, so that reached a producer as a
    # review item on two values that are the same company.
    # It also mis-classified the FORM: `entity_family` reads this function's
    # output, so "Limited Liability Corporation" came back `corporation` and
    # would have ticked the Corporation box for an LLC.
    # Four more equivalences on the same footing, each measured as a live false
    # conflict: Sole Proprietor / Sole Proprietorship, Nonprofit / Non-Profit /
    # Not For Profit, Corporation / Incorporated, Partnership / General
    # Partnership.
    # DELIBERATELY NOT FOLDED, because they are genuinely different entities and
    # principle 4 says a real disagreement stays visible: Limited Partnership
    # and Limited Liability Partnership keep their own tokens (an LP is not a
    # GP), S Corporation keeps its own (its own ACORD box, and a different tax
    # election), and Municipality / Government Entity are left to the producer
    # rather than folded on our own authority (principle 7).
    "limited liability corporation": "llc",
    "limited liability co": "llc",
    "sole proprietorship": "sole prop",
    "sole proprietor": "sole prop",
    "not for profit": "nonprofit",
    "non profit": "nonprofit",
    "nonprofit": "nonprofit",
    "general partnership": "partnership",
    "llc": "llc",
    "professional limited liability company": "pllc",
    "pllc": "pllc",
    "limited liability partnership": "llp",
    "llp": "llp",
    "limited partnership": "lp",
    "lp": "lp",
    # "Acme Inc" and "Acme Corporation" are the same LEGAL ENTITY TYPE, and
    # ACORD prints one Corporation box for both. Folded 2026-08-27 (V1 H4);
    # safe because this table is read by `normalize_entity_type` alone, which
    # is dispatched only for entity_type values - company NAME comparison uses
    # `normalize_name` / `strict_entity_key` and is untouched.
    "incorporated": "corp",
    "inc": "corp",
    "corporation": "corp",
    "corp": "corp",
    "professional corporation": "pc",
    "company": "co",
    "co": "co",
    "limited": "ltd",
    "ltd": "ltd",
}

# Insurance-terminology SYNONYMS (Beta Report §5.2). Variant -> canonical token.
#
# NOTE: "BI = Building" is included per §5.2 client decision (Option C accepted).
# "BI" is ambiguous in commercial insurance (Bodily Injury / Business Interruption
# / Building) but the client accepted global mapping as the report specifies.
_INSURANCE_SYNONYMS = {
    "combined single limit": "csl",
    "csl": "csl",
    "commercial general liability": "cgl",
    "cgl": "cgl",
    "general liability": "gl",
    "gl": "gl",
    "workers compensation": "wc",
    "workers comp": "wc",
    "workmans compensation": "wc",
    "workman s compensation": "wc",
    "wc": "wc",
    "business personal property": "bpp",
    "bpp": "bpp",
    "total insured value": "tiv",
    "tiv": "tiv",
    "employment practices liability insurance": "epli",
    "employment practices liability": "epli",
    "epli": "epli",
    "hired and non owned auto": "hnoa",
    "hired non owned auto": "hnoa",
    "hired and nonowned auto": "hnoa",
    "hnoa": "hnoa",
    "construction occupancy protection exposure": "cope",
    "cope": "cope",
}

# Build a single longest-first replacement table for the general normalizer so
# "commercial general liability" is consumed before "general liability".
_GENERAL_SYNONYMS = dict(_INSURANCE_SYNONYMS)
_GENERAL_SYNONYMS_SORTED = sorted(
    _GENERAL_SYNONYMS.items(), key=lambda kv: len(kv[0]), reverse=True
)
_ENTITY_TYPE_SYNONYMS_SORTED = sorted(
    _ENTITY_TYPE_SYNONYMS.items(), key=lambda kv: len(kv[0]), reverse=True
)


# ── Address terms (Beta Report §5.2) ──────────────────────────────────────────

# Street-suffix words -> USPS-style abbreviation (full word and abbrev compare
# equal).  Keyed by full word; the abbreviation is the canonical token.
_STREET_SUFFIXES = {
    "street": "st", "st": "st",
    "avenue": "ave", "ave": "ave", "av": "ave",
    "road": "rd", "rd": "rd",
    "drive": "dr", "dr": "dr",
    "boulevard": "blvd", "blvd": "blvd",
    "lane": "ln", "ln": "ln",
    "court": "ct", "ct": "ct",
    "place": "pl", "pl": "pl",
    "circle": "cir", "cir": "cir",
    "terrace": "ter", "ter": "ter",
    "parkway": "pkwy", "pkwy": "pkwy",
    "highway": "hwy", "hwy": "hwy",
    "square": "sq", "sq": "sq",
    "trail": "trl", "trl": "trl",
    "way": "way",
}

# Unit / secondary-designator markers dropped entirely so "#D13", "Unit D13",
# "Ste D13" and "D13" all collapse to "d13" (Beta Report §5.2: Suite = Ste,
# Unit = Unit or #, #D13 = D13).
_UNIT_MARKERS = frozenset({
    "suite", "ste", "unit", "apt", "apartment", "no", "number", "rm", "room",
    "fl", "floor", "bldg",
})

# Compass directionals collapsed to their abbreviation so "North Main" and
# "N Main" compare equal. Directionals were not enumerated in §5.2 but follow the
# same suffix-abbreviation intent. DISTINCT directions stay distinct (n != s), so
# this only suppresses formatting noise - it never merges two different addresses.
_DIRECTIONALS = {
    "north": "n", "n": "n",
    "south": "s", "s": "s",
    "east": "e", "e": "e",
    "west": "w", "w": "w",
    "northeast": "ne", "ne": "ne",
    "northwest": "nw", "nw": "nw",
    "southeast": "se", "se": "se",
    "southwest": "sw", "sw": "sw",
}

# US state full names → 2-letter abbreviation for address comparison.
# Multi-word states are listed first so regex replacement consumes the full
# phrase before any single-word subterm can match (e.g. "West Virginia" before
# "Virginia"). Applied as a phrase-level substitution in normalize_address
# BEFORE tokenizing so "Colorado" and "CO" both reduce to "co".
_US_STATE_NAME_PHRASES: List[tuple] = sorted([
    ("district of columbia", "dc"), ("new hampshire", "nh"),
    ("new jersey", "nj"), ("new mexico", "nm"), ("new york", "ny"),
    ("north carolina", "nc"), ("north dakota", "nd"),
    ("rhode island", "ri"), ("south carolina", "sc"),
    ("south dakota", "sd"), ("west virginia", "wv"),
    ("alabama", "al"), ("alaska", "ak"), ("arizona", "az"),
    ("arkansas", "ar"), ("california", "ca"), ("colorado", "co"),
    ("connecticut", "ct"), ("delaware", "de"), ("florida", "fl"),
    ("georgia", "ga"), ("hawaii", "hi"), ("idaho", "id"),
    ("illinois", "il"), ("indiana", "in"), ("iowa", "ia"),
    ("kansas", "ks"), ("kentucky", "ky"), ("louisiana", "la"),
    ("maine", "me"), ("maryland", "md"), ("massachusetts", "ma"),
    ("michigan", "mi"), ("minnesota", "mn"), ("mississippi", "ms"),
    ("missouri", "mo"), ("montana", "mt"), ("nebraska", "ne"),
    ("nevada", "nv"), ("ohio", "oh"), ("oklahoma", "ok"),
    ("oregon", "or"), ("pennsylvania", "pa"), ("tennessee", "tn"),
    ("texas", "tx"), ("utah", "ut"), ("vermont", "vt"),
    ("virginia", "va"), ("washington", "wa"), ("wisconsin", "wi"),
    ("wyoming", "wy"),
], key=lambda x: len(x[0]), reverse=True)


# ── Carrier seed alias map (Beta Report §5.2 carrier handling) ────────────────

# Lightly-normalized carrier name (lowercase, punctuation -> space, collapsed)
# -> canonical family token. Known aliases collapse to one token; everything
# else falls through to a trimmed-name comparison and is surfaced for REVIEW
# (never a definitive hard conflict).
_CARRIER_ALIASES = {
    "emc": "emc",
    "emc insurance": "emc",
    "emc insurance company": "emc",
    "emc insurance companies": "emc",
    "emc property and casualty": "emc",
    "emc property and casualty company": "emc",
    "employers mutual casualty": "emc",
    "employers mutual casualty company": "emc",
}


# ── Low-level cleaners ────────────────────────────────────────────────────────

def _basic(s: Any) -> str:
    """Lowercase, replace '&' with 'and', drop punctuation, collapse whitespace.

    Dotted initialisms are collapsed first (N.A. -> na, L.L.C. -> llc, U.S.A. ->
    usa) so periods are truly ignored per Beta Report §5.2 and a dotted entity
    suffix matches its plain form. Only sequences of 2+ single-letter-dot groups
    are collapsed, so "St.Mary" (glued OCR) and "Inc." are left untouched.
    """
    if s is None:
        return ""
    s = str(s).lower().replace("&", " and ")
    s = re.sub(r"(?:\b[a-z]\.){2,}", lambda m: m.group(0).replace(".", ""), s)
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ── Public normalizers ────────────────────────────────────────────────────────

def normalize_name(value: Any) -> str:
    """Organization name for identity comparison.

    Lowercase, drop punctuation/commas/periods, collapse whitespace, and strip
    trailing entity suffixes (LLC / Inc / Corp / Limited Liability Company / ...)
    so "ORBIN CONTRACTING LLC", "Orbin Contracting LLC" and "Orbin Contracting,
    LLC" all reduce to "orbin contracting". Returns '' when no usable signal.
    """
    s = _basic(value)
    if not s:
        return ""
    changed = True
    while changed:
        changed = False
        for suf in _ENTITY_SUFFIXES:
            if s == suf:
                return ""
            if s.endswith(" " + suf):
                s = s[: -(len(suf) + 1)].strip()
                changed = True
    return s


_DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d",
    "%m/%d/%Y", "%m/%d/%y",
    "%m-%d-%Y", "%m-%d-%y",
    "%m.%d.%Y", "%m.%d.%y",
    "%B %d %Y", "%b %d %Y",
    "%d %B %Y", "%d %b %Y",
    # DD-Mon-YYYY, the form carrier and agency-management systems export
    # ("15-Jul-2025", "15/Jul/25"). Found by the 2026-09-05 fuzz sweep, where
    # `15-Jul-2025` vs `07/15/2025` came back a CONFLICT - a pure formatting
    # difference producing a warning, which is exactly what the client's
    # broader normalization clause forbids.
    #
    # SAFE BECAUSE THE MONTH IS A NAME. Day-first NUMERIC ("15/07/2025") is
    # deliberately still unparsed and must stay that way: "05/09/2026" is the
    # 5th of September or the 9th of May and nothing in the string can decide
    # which, so parsing it would invent a date rather than normalise one.
    # Compact "20250715" is likewise excluded - `same_fact`'s value-shape
    # fallback tries `normalize_date` on non-date fields too, so an 8-digit
    # account or policy number would start reading as a date.
    "%d-%B-%Y", "%d-%b-%Y", "%d-%B-%y", "%d-%b-%y",
    "%d/%B/%Y", "%d/%b/%Y", "%d/%B/%y", "%d/%b/%y",
    "%B-%d-%Y", "%b-%d-%Y", "%B-%d-%y", "%b-%d-%y",
)


def normalize_date(value: Any) -> Optional[str]:
    """Canonical ISO date ('YYYY-MM-DD'), or None if not parseable.

    Treats "07/15/25", "7/15/2025", "07/15/2025" and "2025-07-15" as equal.
    Two-digit years pivot at 70 (00-69 -> 2000s, 70-99 -> 1900s), appropriate
    for policy dates. Returns None when the value cannot be parsed as a date so
    the caller can fall back to text comparison.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Strip an ordinal suffix and a leading weekday/commas for the written forms.
    s = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", s, flags=re.IGNORECASE)
    s = s.replace(",", " ")
    s = re.sub(r"\s+", " ", s).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def normalize_entity_type(value: Any) -> str:
    """Entity-type to a canonical token. "LLC" == "Limited Liability Company".

    Extraction sometimes returns a concatenated PascalCase value with no spaces
    ("LimitedLiabilityCompany" - seen from schema-driven form fields such as
    ACORD's own entity-type enum). The synonym match below is word-boundary
    based, so it would silently miss that form and treat it as a different
    entity type than "Limited Liability Company" / "LLC". Splitting camelCase
    into words FIRST (before lowercasing) recovers the word boundaries so all
    three forms collapse to the same canonical token.
    """
    raw = "" if value is None else str(value)
    raw = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", raw)
    s = _basic(raw)
    if not s:
        return ""
    for variant, canon in _ENTITY_TYPE_SYNONYMS_SORTED:
        s = re.sub(rf"\b{re.escape(variant)}\b", canon, s)
    return re.sub(r"\s+", " ", s).strip()


# ── Legal-entity FAMILIES - V1 H4 (client section 9), 2026-08-27 ─────────────
# `normalize_entity_type` above answers "are these two the same entity type?"
# (the COMPARATOR's question, D3). It does NOT answer "which of ACORD's nine
# legal-entity boxes is this?", and three separate places were each guessing at
# that in their own vocabulary:
#
#   * FACT_REGISTRY["entity_type"]["validate"] - a literal 16-item uppercase set
#     that REFUSED 8 of the 13 options `answer_options` itself offers
#     ("Limited Liability Company", "S Corporation", "Joint Venture", ...), so a
#     producer picking from our own dropdown was told "that does not look right";
#   * `answer_options.ENTITY_TYPE_OPTIONS` - a third list, written independently;
#   * `pdf_service._derive_indicator` - an inline "limited liability company ->
#     llc" phrase loop plus substring matching, which ticked NO box for
#     "Sole Proprietorship" (ACORD's box is Individual), ticked Corporation for
#     "S Corporation", ticked BOTH Corporation and NotForProfit for "Non-Profit
#     Corporation", and ticked nothing at all for "Association" / "Municipality"
#     while asserting "No" on the Other box that exists precisely for them.
#
# ACORD's own tooltip settles the shape and it is quoted here so nobody has to
# re-derive it: *"Indicates the legal entity CODE for the named insured IS
# 'Corporation'"* - singular. The nine indicators are MUTUALLY EXCLUSIVE, and
# `NamedInsured_LegalEntity_OtherIndicator_*` pairs with
# `NamedInsured_LegalEntity_OtherDescription_*` for anything not listed.
#
# THIS IS ADDITIVE AND MUST STAY ADDITIVE. `normalize_entity_type` is untouched,
# so every conflict / equivalence decision that reads it (fact_comparison ->
# fact_equivalence -> underwriting_consistency, D3's one comparator door) behaves
# exactly as before. This function only ever CLASSIFIES.
#
# Verified 2026-08-27 to be a strict SUPERSET of the validator it replaces:
# all 16 values the old literal set accepted still map to a family, and all 13
# offered options now validate. Nothing that validated before stops validating.
ENTITY_FAMILY_INDIVIDUAL = "individual"
ENTITY_FAMILY_PARTNERSHIP = "partnership"
ENTITY_FAMILY_LLC = "llc"
ENTITY_FAMILY_CORPORATION = "corporation"
ENTITY_FAMILY_S_CORPORATION = "s_corporation"
ENTITY_FAMILY_NOT_FOR_PROFIT = "not_for_profit"
ENTITY_FAMILY_JOINT_VENTURE = "joint_venture"
ENTITY_FAMILY_TRUST = "trust"
ENTITY_FAMILY_OTHER = "other"

ENTITY_FAMILIES = (
    ENTITY_FAMILY_INDIVIDUAL, ENTITY_FAMILY_PARTNERSHIP, ENTITY_FAMILY_LLC,
    ENTITY_FAMILY_CORPORATION, ENTITY_FAMILY_S_CORPORATION,
    ENTITY_FAMILY_NOT_FOR_PROFIT, ENTITY_FAMILY_JOINT_VENTURE,
    ENTITY_FAMILY_TRUST, ENTITY_FAMILY_OTHER,
)

# ORDER IS LOAD-BEARING - most specific family first. Every one of these three
# orderings is a real case that the previous substring matching got wrong:
#   not_for_profit BEFORE corporation   -> "Non-Profit Corporation" is not a
#                                          plain Corporation (it ticked BOTH)
#   s_corporation  BEFORE corporation   -> "S Corporation" has its own ACORD box
#   llc            BEFORE partnership   -> guards the LLC/LLP pair
# Matched on WHOLE WORDS of the canonical token `normalize_entity_type` returns,
# never as bare substrings, so "corp" inside "s corp" cannot win by position.
_ENTITY_FAMILY_RULES = (
    (ENTITY_FAMILY_NOT_FOR_PROFIT, ("not for profit", "nonprofit", "non profit",
                                    "charitable", "501 c 3")),
    (ENTITY_FAMILY_S_CORPORATION, ("s corp", "subchapter s", "scorp")),
    (ENTITY_FAMILY_JOINT_VENTURE, ("joint venture", "jv")),
    (ENTITY_FAMILY_LLC, ("llc", "pllc", "limited liability co",
                         "limited liability company", "limited liability corp")),
    (ENTITY_FAMILY_TRUST, ("trust",)),
    (ENTITY_FAMILY_PARTNERSHIP, ("partnership", "llp", "lp",
                                 "limited partnership", "general partnership")),
    (ENTITY_FAMILY_INDIVIDUAL, ("individual", "sole proprietor", "sole prop",
                                "sole proprietorship", "proprietor",
                                "self employed")),
    (ENTITY_FAMILY_CORPORATION, ("corporation", "corp", "incorporated", "inc", "pc")),
    # Everything ACORD does not print a box for. These are REAL entity types, so
    # they belong on the form's Other box with their own wording in
    # OtherDescription - not silently unticked, which is what happened before.
    (ENTITY_FAMILY_OTHER, ("association", "municipality", "government",
                           "governmental", "public entity", "unincorporated",
                           "cooperative", "co op", "religious", "church",
                           "school district", "other")),
)


def entity_family(value: Any) -> Optional[str]:
    """Which ACORD legal-entity family is this, or None when we cannot tell.

    None is a real answer and callers MUST honour it: core principle 3 says a
    value we cannot classify never becomes a "No". The stamper ticks NOTHING for
    None rather than asserting the named insured is none of the nine, and the
    validator refuses it rather than storing an entity type no form can express.

    Positive evidence only, and never a guess: "Ltd" alone stays None (a UK
    private company and a US "Acme Ltd" trade name are not distinguishable here),
    which is the right-or-blank rule this codebase applies everywhere else.
    """
    s = normalize_entity_type(value)
    if not s:
        return None
    # Pad and strip punctuation so every probe below is a WHOLE-WORD test.
    s = " " + re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s)).strip() + " "
    for family, words in _ENTITY_FAMILY_RULES:
        for word in words:
            if f" {word} " in s:
                return family
    return None


def normalize_address(value: Any) -> str:
    """Street address for comparison.

    Lowercases, treats '#' as a separator, expands/collapses full US state names
    to their 2-letter abbreviation (Colorado->co, New York->ny, ...), truncates a
    ZIP+4 to its 5-digit ZIP (80216-3121 == 80216 - the first 5 digits ARE the
    ZIP5, so a ZIP+4 is strictly more precision on the SAME delivery point, not a
    different one - collapsing it here is what lets the picker treat them as one
    address instead of an unresolved conflict), drops punctuation, maps
    street-suffix words to their abbreviation (Street->st, Avenue->ave, ...),
    standardizes compass directionals (North->n, ...), and removes unit markers
    (Suite/Ste/Unit/#) so "4800 DAHLIA ST #D13" and "4800 Dahlia Street Suite
    D13, Denver, Colorado 80216-3121" both reduce to the same token string.
    """
    if value is None:
        return ""
    s = str(value).lower().replace("#", " ")
    # ZIP+4 -> ZIP5, BEFORE punctuation stripping turns the hyphen into a bare
    # space (which would otherwise leave the extra 4 digits as an unmatched
    # trailing token and manufacture a false conflict against a ZIP5-only value).
    s = re.sub(r"\b(\d{5})-\d{4}\b", r"\1", s)
    # Substitute full state names before stripping punctuation so multi-word
    # names ("New York", "West Virginia") are caught as phrases. Longest phrases
    # are applied first (see _US_STATE_NAME_PHRASES sort order).
    for phrase, abbrev in _US_STATE_NAME_PHRASES:
        s = re.sub(rf"\b{re.escape(phrase)}\b", abbrev, s)
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    # Compass directionals collapse to their abbreviation HERE, before the
    # unit-join below - not in the token loop. The order is load-bearing and
    # getting it wrong was a real bug (found 2026-08-21 probing C1-C): the join
    # fired on "E 9 Mile Rd" -> "e9 mile rd" while "East 9 Mile Rd" stayed
    # "e 9 mile rd", so two printings of ONE address became a conflict - the
    # exact defect class this module exists to prevent. Normalising first makes
    # both sides identical before anything can glue them.
    s = re.sub(
        r"\b(north|south|east|west|northeast|northwest|southeast|southwest)\b",
        lambda m: _DIRECTIONALS[m.group(1)], s)
    # A unit marker glued to its number ("Apt4", "Ste12") is the same unit as
    # the spaced form; splitting it lets the marker be dropped like any other.
    s = re.sub(r"\b(suites?|ste|units?|apt|apartment|rm|room|fl|floor|bldg)(\d)",
               r"\1 \2", s)
    # A unit designator printed as letter + separator + digits ("D-13", "D 13",
    # "Suite B 5") is the same unit as "D13" / "B5": OCR and form layouts split
    # it unpredictably (V1 plan C1-B FLAG 3 - the hyphen inside the unit was
    # the one printing the picker could not fold). DIRECTIONAL letters are
    # excluded: "E 9" is East 9th - a street name, not unit E9.
    s = re.sub(r"\b(?!(?:n|s|e|w|ne|nw|se|sw)\b)([a-z])\s+(\d+[a-z]?)\b",
               r"\1\2", s)
    tokens = s.split()
    out: List[str] = []
    for tok in tokens:
        if tok in _UNIT_MARKERS:
            continue
        tok = _DIRECTIONALS.get(tok, tok)
        out.append(_STREET_SUFFIXES.get(tok, tok))
    return " ".join(out).strip()


def normalize_carrier(value: Any) -> str:
    """Carrier name to a canonical token.

    Known aliases (seed map) collapse to a family token (EMC ↔ Employers Mutual
    Casualty). Otherwise generic insurer-suffix words are stripped and the
    remaining name tokens are returned for comparison. Carrier differences are
    treated as REVIEW (not a hard conflict) by the caller.
    """
    s = _basic(value)
    if not s:
        return ""
    if s in _CARRIER_ALIASES:
        return _CARRIER_ALIASES[s]
    # Strip generic insurer descriptors so "EMC Property and Casualty Company"
    # and "EMC Insurance" both reduce toward "emc".
    _GENERIC = {
        "insurance", "company", "companies", "casualty", "property", "mutual",
        "group", "co", "inc", "corp", "ins", "and", "of", "the", "national",
        "indemnity", "underwriters", "assurance", "general",
    }
    tokens = [t for t in s.split() if t not in _GENERIC]
    trimmed = " ".join(tokens).strip()
    # Re-check the alias map against the trimmed token (catches "emc" alone).
    if trimmed in _CARRIER_ALIASES:
        return _CARRIER_ALIASES[trimmed]
    return trimmed or s


_VALUATION_METHOD_CANON = {
    "rcv": "rcv", "r": "rcv", "replacement cost": "rcv", "replacement cost value": "rcv",
    "acv": "acv", "a": "acv", "actual cash value": "acv",
    "agreed amount": "agreed_amount", "v": "agreed_amount",
    "market value": "market_value", "m": "market_value",
}


def normalize_valuation_method(value: Any) -> str:
    """Canonical valuation-method key - "RCV"/"R"/"Replacement Cost" (and the
    ACV/Agreed-Amount/Market-Value equivalents) all collapse to the same
    comparison key, regardless of whether the value came from the extraction-
    normalized 3-letter industry term or the ACORD schema's own single-letter
    code convention. See VALUATION_METHOD_FIELDS for why this is its own
    narrow, field-scoped normalizer rather than a generic synonym expansion.
    """
    s = _basic(value)
    if not s:
        return ""
    return _VALUATION_METHOD_CANON.get(s, s)


def normalize_fein(value: Any) -> str:
    """Digits-only FEIN. Returns '' unless exactly 9 digits (a complete US FEIN).

    A US FEIN/EIN is exactly 9 digits. Requiring an exact length (rather than ">=
    9") means an over-long OCR/extraction artifact normalizes to '' (no signal,
    treated as absent) instead of a distinct value that could manufacture a false
    cross-document FEIN conflict. Mirrors the rule in submission_integrity so the
    two modules agree.
    """
    if value is None:
        return ""
    digits = re.sub(r"\D", "", str(value))
    return digits if len(digits) == 9 else ""


def normalize_general(value: Any) -> str:
    """General fallback for any scalar field with no dedicated normalizer.

    Expands insurance-terminology synonyms (CSL == Combined Single Limit,
    CGL == Commercial General Liability, ...), collapses currency/number
    formatting ($1,000,000 == 1000000 == 1,000,000.00), and strips punctuation.
    """
    if value is None:
        return ""
    s = str(value).lower().replace("&", " and ")
    # Drop currency symbols and thousands separators before synonym expansion.
    s = s.replace("$", " ")
    s = re.sub(r"(?<=\d),(?=\d)", "", s)        # 1,000,000 -> 1000000
    # Replace remaining punctuation with spaces so phrases tokenize cleanly.
    s = re.sub(r"[^a-z0-9.\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for variant, canon in _GENERAL_SYNONYMS_SORTED:
        s = re.sub(rf"\b{re.escape(variant)}\b", canon, s)
    # Drop insignificant trailing decimals: 1000000.00 -> 1000000, 12.50 -> 12.5
    s = re.sub(r"(\d)\.0+\b", r"\1", s)
    s = re.sub(r"(\d\.\d*?)0+\b", r"\1", s)
    s = re.sub(r"(\d)\.\b", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


# ── Dispatcher ────────────────────────────────────────────────────────────────

def _normalize_date_or_general(value: Any) -> str:
    """ISO date when parseable, else the general text normalization.

    Shared by the explicit DATE_FIELDS and any inferred "_date" key so both paths
    behave identically: a real date compares by calendar value, while an
    un-date-like string still compares as text rather than collapsing to ''.
    """
    iso = normalize_date(value)
    # Unparseable dates fall back to general text so two genuinely different
    # un-date-like strings still differ rather than both collapsing to ''.
    return iso if iso is not None else normalize_general(value)


def normalize_value(field: str, value: Any) -> str:
    """Return the canonical COMPARISON string for ``value`` given its fact key.

    Dispatch order: the explicit *_FIELDS sets first (authoritative), then a
    shape-based inference fallback (_infer_field_category) so a secondary or new
    key of a known type is still normalized correctly instead of dropping to the
    generic normalizer. '' means "no usable signal" — the caller treats it as
    absent so a missing/garbage value never manufactures a conflict.
    """
    # 1. Explicit category sets — authoritative; never changes existing behavior.
    if field in NAME_FIELDS:
        return normalize_name(value)
    if field in DATE_FIELDS:
        return _normalize_date_or_general(value)
    if field in ENTITY_TYPE_FIELDS:
        return normalize_entity_type(value)
    if field in ADDRESS_FIELDS:
        return normalize_address(value)
    if field in CARRIER_FIELDS:
        # A rating bureau on a carrier field carries NO signal - "" is what this
        # dispatcher returns for "nothing usable here", and every caller already
        # treats that as absent. So the picker never offers it as a rival
        # carrier and the comparison layer never calls it a conflict.
        if is_insurance_bureau(value):
            return ""
        return normalize_carrier(value)
    if field in FEIN_FIELDS:
        return normalize_fein(value)
    if field in VALUATION_METHOD_FIELDS:
        return normalize_valuation_method(value)
    # 1b. Yes/No (SYS-07). Placed AFTER the explicit identity sets - those are
    #     authoritative and no key belongs to both - and BEFORE the shape
    #     inference and the generic normalizer, which is what used to make
    #     "Yes" and "X" two different comparison keys. A value that is not a
    #     bare Yes/No token ("Yes - see attached") gets no opinion here and
    #     falls through to the ordinary text path exactly as before.
    if is_yes_no_field(field):
        canon = canonical_yes_no(value)
        if canon:
            return canon.lower()
    # 2. Shape-based inference for keys outside the explicit sets (Beta Report §5:
    #    normalization must be generic for any document, not only canonical keys).
    category = _infer_field_category(field)
    if category == "date":
        return _normalize_date_or_general(value)
    if category == "address":
        return normalize_address(value)
    if category == "carrier":
        return normalize_carrier(value)
    if category == "name":
        return normalize_name(value)
    # 3. Generic fallback (insurance synonyms, currency, punctuation).
    return normalize_general(value)


# ── Strict entity identity (audit 2026-08-15 round 10) ───────────────────────
# The coarse normalizers above are EQUIVALENCE tools: normalize_carrier
# collapses a carrier GROUP's printings to one family token (right for
# document clustering and the foreign-entity drop), normalize_name strips the
# entity suffix (right for matching a suffixless COI mention to the insured).
# Used as the CONFLICT comparator they are blind by construction: EMC Property
# & Casualty vs Employers Mutual Casualty both reduce to "emc", and Orbin
# Contracting LLC vs Orbin Contracting Inc both reduce to "orbin contracting" -
# so the reconciler pronounced the two REAL carriers on the client's package
# consistent and the picker never opened. That is client complaint #2 at its
# root, one layer above every stamping guard.
#
# The strict layer keeps every distinguishing word and canonicalizes only
# SPELLING (Co./Company, Inc/Incorporated, L.L.C./Limited Liability Company).
# Compatibility is token-SUBSET: a truncation ("Travelers" vs "Travelers
# Indemnity Company", a suffixless name vs its suffixed form) is the same
# entity under-specified; two names that EACH carry a word the other lacks
# (Property+Casualty vs Employers+Mutual, LLC vs Inc, Fire vs Casualty) are
# different entities and MUST conflict.
_STRICT_PHRASE_CANON: List[Tuple[str, str]] = [
    ("limited liability company", "llc"),
    ("limited liability co", "llc"),
    ("limited liability corporation", "llc"),
    ("limited partnership", "lp"),
    ("limited liability partnership", "llp"),
    ("professional corporation", "pc"),
]
_STRICT_TOKEN_CANON: Dict[str, str] = {
    "llc": "llc", "pllc": "pllc", "lp": "lp", "llp": "llp", "pc": "pc",
    "ltd": "ltd", "limited": "ltd",
    "inc": "inc", "incorporated": "inc",
    "corp": "corp", "corporation": "corp",
    "co": "company", "cos": "company", "company": "company", "companies": "company",
    "ins": "insurance", "insurance": "insurance",
    "assur": "assurance", "assurance": "assurance",
    "indem": "indemnity", "indemnity": "indemnity",
    "mut": "mutual", "mutual": "mutual",
    "cas": "casualty", "casualty": "casualty",
    "natl": "national", "national": "national",
    "grp": "group", "group": "group",
    # ── Added 2026-08-23. The client's opening paragraph names ABBREVIATIONS
    # as one of the differences that must not become a contradiction, and the
    # table already expanded `cas`/`co`/`mut` but stopped short. Measured on the
    # live package: `EMC Prop & Cas Co` and `EMC Property & Casualty Company`
    # keyed as `emc prop casualty company` vs `emc property casualty company` -
    # two "different entities" over one missing expansion. Same for
    # `Travelers Prop Cas Co of Am` vs `...Company of America`.
    #
    # THESE CANNOT FOLD TWO REAL CARRIERS. Every entry expands a CORPORATE-FORM
    # or GEOGRAPHIC word, never the distinguishing name: `EMC Property &
    # Casualty` and `Employers Mutual Casualty` still differ on `emc` vs
    # `employers mutual`, which is Round 10 fix 46 and is pinned by test.
    "prop": "property", "property": "property",
    "amer": "america", "am": "america", "america": "america",
    "american": "america",          # the qualifier, not a distinguishing name
    "intl": "international", "international": "international",
    "gen": "general", "general": "general",
    "assn": "association", "association": "association",
    "fin": "financial", "financial": "financial",
    "svc": "services", "svcs": "services", "serv": "services",
    "services": "services", "service": "services",
    "guar": "guaranty", "guaranty": "guaranty",
    "exch": "exchange", "exchange": "exchange",
    "reins": "reinsurance", "reinsurance": "reinsurance",
    "agcy": "agency", "agency": "agency",
    "underwrs": "underwriters", "underwriters": "underwriters",
}
_STRICT_NOISE_TOKENS = frozenset({"the", "of", "and", "a", "an"})


def _strict_entity_tokens(value: Any) -> FrozenSet[str]:
    s = _basic(value)
    if not s:
        return frozenset()
    for phrase, canon in _STRICT_PHRASE_CANON:
        s = re.sub(rf"\b{re.escape(phrase)}\b", canon, s)
    return frozenset(
        _STRICT_TOKEN_CANON.get(t, t)
        for t in s.split() if t not in _STRICT_NOISE_TOKENS)


def strict_entity_key(value: Any) -> str:
    """Spelling-canonical, distinction-preserving comparison key for a legal
    entity name (person, organization, or carrier)."""
    s = _basic(value)
    if not s:
        return ""
    for phrase, canon in _STRICT_PHRASE_CANON:
        s = re.sub(rf"\b{re.escape(phrase)}\b", canon, s)
    out = [_STRICT_TOKEN_CANON.get(t, t)
           for t in s.split() if t not in _STRICT_NOISE_TOKENS]
    return " ".join(out)


def entity_identity_conflict(raw_values: List[Any]) -> bool:
    """True when two values name MATERIALLY different legal entities.

    Token-subset compatibility: equal sets, or one a subset of the other
    (truncation / missing suffix), are the same entity. Each carrying a token
    the other lacks is a real disagreement the review picker must surface.
    """
    keys = [t for t in (_strict_entity_tokens(v) for v in raw_values) if t]
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            if not (a <= b or b <= a):
                return True
    return False


def distinct_normalized(field: str, raw_values: List[Any]) -> Set[str]:
    """Set of non-empty normalized comparison keys for ``raw_values``.

    ``len(...) > 1`` means the values MATERIALLY differ after normalization and
    a conflict is warranted; ``<= 1`` means they are equivalent (formatting-only
    difference) and no conflict should be raised.
    """
    return {n for v in raw_values if (n := normalize_value(field, v))}


def values_conflict(field: str, raw_values: List[Any]) -> bool:
    """True when ``raw_values`` materially differ after normalization."""
    return len(distinct_normalized(field, raw_values)) > 1


# ── Loss-history no-loss assertion detector ───────────────────────────────────
# Single source of truth shared by extraction_pipeline.py (drives the
# narrative_states_no_losses flag that feeds SQS scoring) and pdf_service.py
# (drives the LossHistory_NoPriorLossesIndicator_A "Check if none" checkbox).
# Previously these were two independent detectors: the SQS side used this
# phrase scan, the PDF checkbox was decided by a separate, unrelated GPT
# per-field judgment call - so the checkbox could come back "Yes" (checked,
# reads as confirmed) while the SQS panel simultaneously called the exact same
# submission "an assertion, weaker than an attestation, please confirm". Both
# surfaces now call this one function, so they can no longer disagree.
_NO_LOSS_PHRASES = (
    "no prior losses", "no losses", "no prior claims", "no claims",
    # "no known losses" is the single most common industry phrasing and is NOT
    # a superset of "no losses" (the word "known" sits between them), so it
    # must be listed explicitly. Same for the "reported"/"free" variants.
    "no known losses", "no known claims",
    "no reported losses", "no reported claims",
    "loss-free", "loss free", "claims-free", "claims free",
    "clean loss history", "favorable loss history", "clean loss record",
)
# Standard ACORD/loss-run boilerplate reads "...no claims exceeding $10,000"
# and real loss-run summaries say "no losses exceed $10,000" / "no losses over
# $X" - a THRESHOLD statement (losses exist, none cross the cap), not a
# zero-loss assertion. A bare substring match on "no losses" misreads that as
# a no-loss assertion even when real claims are attached. Skip a phrase hit
# when immediately followed by a threshold qualifier.
_NO_LOSS_QUALIFIERS = (
    "exceed", "exceeding", "over", "above", "in excess", "greater than", "more than",
)


# A qualifier only makes a THRESHOLD when an AMOUNT follows it.
#
# LIVE 2026-09-08. "over" was listed to catch "no losses over $10,000", but it
# matched on the next 20 characters with nothing checking that a figure came
# next - so the far more common TIME phrasing
#
#     "No losses over the past five years"
#
# was read as a threshold and `detect_no_loss_assertion` returned False. That is
# a producer's genuine attestation being discarded. It surfaced the moment
# `pdf_service._attests_no_loss` began delegating here: the ACORD 125
# "Check if none" box went from ticked to printing an explicit **No** - a signed
# form asserting the opposite of what the producer typed.
#
# The distinction is what follows the qualifier: a threshold names a SUM, a time
# phrase names a PERIOD. "greater than" / "in excess" are kept unconditional -
# they are never used to introduce a time span in this vocabulary.
_AMOUNT_AFTER_QUALIFIER_RE = re.compile(r"^[\s:$£€]*\d")
_TIME_QUALIFIERS = frozenset({"over", "above", "more than"})


# A NO-LOSS CLAIM THAT CARRIES A LOSS AMOUNT CONTRADICTS ITSELF.
#
# The phrase scan reads the first few words and stops, so
#
#     "Clean loss history apart from a $40,000 fire in 2023"
#
# returned True - the $40,000 fire, the entire point of the sentence, was never
# read. It scored the account 60 ("attested no losses"), and once
# `pdf_service._attests_no_loss` began delegating here it also TICKED the ACORD
# 125 "Check if none" box: a signed form asserting no losses on an account with
# a fire.
#
# WHY THIS IS A MONEY TEST AND NOT A LIST OF EXCEPTION WORDS. "apart from",
# "except", "other than", "aside from", "but for", "save for", "excluding" ...
# is an open set, and an open set is the allow-list this project's quality bar
# forbids - you are always one phrasing behind. A NON-ZERO AMOUNT is structural:
# a genuine no-loss statement never needs one, and a loss worth excepting almost
# always carries its number. Peril words ("fire", "accident") were tried and
# REJECTED - they co-occur with the negation itself ("no claims or accidents in
# the past 5 years"), so they refuse genuine attestations.
#
# SCOPED TO THE PHRASE'S OWN CLAUSE. Scanning the document would refuse every
# no-loss sentence on every dec page, since dec pages are made of dollar amounts.
#
# ZERO IS EXEMPT: "no losses, total incurred $0" is a no-loss statement stating
# its own zero, and blanking that would be the opposite of the intent.
#
# HONEST LIMIT: "clean loss history apart from one fire" carries no figure and
# still reads as an attestation. That is not covered, and no rule of this shape
# will cover it. The guarantee is the FAILURE DIRECTION - what this does catch
# resolves to blank-and-ask, never to a false "yes" on a signed form.
_LOSS_CLAUSE_BREAK = ".;!?\n\r"
_LOSS_CLAUSE_WINDOW = 200
_NONZERO_AMOUNT_RE = re.compile(
    r"(?:[$£€]\s?|\b)(?!0+(?:[.,]0+)*\b)\d[\d,]*(?:\.\d+)?\s*(?:k\b|m\b|dollars\b)?"
)
_MONEY_SHAPE_RE = re.compile(r"[$£€]\s?\d|\d[\d,]*\d\s*dollars\b|\b\d{1,3}(?:,\d{3})+\b")


# AN EXCEPTION HAS A GRAMMAR, AND THAT GRAMMAR IS A CLOSED CLASS.
#
# The money rule above catches an exception that names a figure. It does not
# catch "clean loss history apart from ONE FIRE" - no amount, so nothing
# contradicts the phrase, and it attests.
#
# THE CORRECTION THAT MADE THIS FIXABLE. This was first written off as
# unfixable, on the grounds that exception wording is infinite. It is not. What
# is infinite is the LOSS - "a fire", "the slip and fall", "that thing with the
# forklift" - which is why no list of PERILS can work and why the money rule
# names none. But the words that JOIN "everything clean" to "this one thing" are
# a closed grammatical class: exceptive prepositions and conjunctions. English
# has roughly fifteen and coins no more, the way it coins nouns.
#
# So the two rules split the space by what each can bound:
#   * an exception carrying a FIGURE      -> the money rule, no vocabulary at all
#   * an exception carrying no figure     -> this rule, a closed function-word set
#
# NEITHER touches a coordination inside the negation's own scope - "no claims OR
# ACCIDENTS in the past 5 years" has no amount and no exceptive, so it still
# attests. That case is what killed the peril-word approach and it is the
# control for this one.
#
# TAIL ONLY, deliberately. A leading exceptive ("Other than the fire, clean loss
# history") is not caught: checking the head would refuse legitimate preambles
# like "Per our review of the loss runs, no known losses". Rarer shape, and the
# money rule still covers it whenever a figure appears. Recorded, not hidden.
_EXCEPTIVE_MARKERS = (
    "except", "excepting", "excluding", "exclusive of",
    "apart from", "aside from", "other than", "otherwise than",
    "besides", "barring", "save for", "save that", "but for",
    "with the exception", "outside of", "notwithstanding",
    "aside of", "bar for",
)


def _tail_introduces_an_exception(tail: str) -> bool:
    """Does the text after a no-loss phrase carve something out of it?"""
    return any(m in tail for m in _EXCEPTIVE_MARKERS)


def _clause_states_a_loss(lowered: str, idx: int) -> bool:
    """Does the clause holding this no-loss phrase also state a loss amount?"""
    lo = max(0, idx - _LOSS_CLAUSE_WINDOW)
    clause = lowered[lo: idx + _LOSS_CLAUSE_WINDOW]
    for ch in _LOSS_CLAUSE_BREAK:
        cut = clause.rfind(ch, 0, idx - lo)
        if cut >= 0:
            clause = clause[cut + 1:]
            idx = idx - lo - cut - 1
            lo = 0
    for ch in _LOSS_CLAUSE_BREAK:
        cut = clause.find(ch, max(0, idx))
        if cut >= 0:
            clause = clause[:cut]
    for m in _MONEY_SHAPE_RE.finditer(clause):
        digits = re.sub(r"[^\d]", "", m.group())
        if digits and int(digits) > 0:
            return True
    return False


def _tail_is_a_threshold(tail: str) -> bool:
    """Does the text right after a no-loss phrase qualify it into a threshold?"""
    for q in _NO_LOSS_QUALIFIERS:
        if not tail.startswith(q):
            continue
        if q in _TIME_QUALIFIERS:
            # Ambiguous word - only a figure makes it a threshold.
            return bool(_AMOUNT_AFTER_QUALIFIER_RE.match(tail[len(q):]))
        return True
    return False


def detect_no_loss_assertion(text: str) -> bool:
    """True if ``text`` contains an unqualified "no losses/claims" assertion.

    Case-insensitive substring scan for common industry no-loss phrasing,
    guarded against threshold statements ("no losses exceed $10,000") that
    read as a match but actually mean the opposite (losses exist, capped).
    """
    if not text:
        return False
    lowered = text.lower()
    for phrase in _NO_LOSS_PHRASES:
        start = 0
        while True:
            idx = lowered.find(phrase, start)
            if idx == -1:
                break
            after = lowered[idx + len(phrase): idx + len(phrase) + _LOSS_CLAUSE_WINDOW]
            for _brk in _LOSS_CLAUSE_BREAK:
                _cut = after.find(_brk)
                if _cut >= 0:
                    after = after[:_cut]
            tail = after[:24].lstrip()
            if (not _tail_is_a_threshold(tail)
                    and not _tail_introduces_an_exception(after)
                    and not _clause_states_a_loss(lowered, idx)):
                return True
            start = idx + len(phrase)
    return False
