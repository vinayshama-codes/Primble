"""fact_state.py - what we KNOW about a fact, on two axes (V1 plan C1 F5, D2).

Client 1.3 and 1.4, verbatim vocabulary. A fact envelope gains two additive
keys; nothing that reads ``value`` / ``confidence`` / ``source`` changes.

VALUE STATE (1.3) - what the value IS
    present                a usable value exists
    explicit_no            a source or a human explicitly states the item does
                           not exist / the answer is no
    not_stated             applicable, but no value or explicit answer found
    not_applicable         does not apply to this account / coverage / exposure
    unable_to_determine    relevant source material exists but the answer could
                           not be reliably determined (a guard rejected it)
    conflicting            two or more materially incompatible values remain
                           after normalisation and scope matching

EVIDENCE STATE (1.4) - how we KNOW it
    source_verified        explicitly and unambiguously supported by source text
    user_confirmed         supplied or confirmed by a producer or client; the
                           actor stays separately identifiable (``evidence_actor``)
    derived                deterministically calculated from supported facts
    suggested              inferred or proposed; not strong enough to be verified

THE 125 DOC'S FOUR (VERIFIED / CONFIRMED / NOT APPLICABLE / UNRESOLVED) are the
DISPLAY projection of these two axes - see :func:`display_state`. ``ASSUMED``
is unrepresentable on either axis, on purpose: the client names it as where the
hallucination problem starts.

THE ONE RULE CONSUMERS MUST HONOUR: only ``present`` and ``explicit_no`` ever
enter a comparison. ``not_stated`` is never compared, never scored as a
disagreement, and never becomes a No (Principle 3). Defect B8 - a boolean
``False`` that meant "this COI never mentioned subcontractors" manufactured a
cross-document conflict and an 85 cap - is the concrete case.

Everything here is DERIVED from signals the pipeline already writes. No new
judgment is made; where no signal exists the honest answer is recorded (a
bare extracted boolean False is ``not_stated``, not ``explicit_no``).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

# ── Vocabulary ───────────────────────────────────────────────────────────────
PRESENT = "present"
EXPLICIT_NO = "explicit_no"
NOT_STATED = "not_stated"
NOT_APPLICABLE = "not_applicable"
UNABLE_TO_DETERMINE = "unable_to_determine"
CONFLICTING = "conflicting"
VALUE_STATES = frozenset({PRESENT, EXPLICIT_NO, NOT_STATED, NOT_APPLICABLE,
                          UNABLE_TO_DETERMINE, CONFLICTING})

SOURCE_VERIFIED = "source_verified"
USER_CONFIRMED = "user_confirmed"
DERIVED = "derived"
SUGGESTED = "suggested"
EVIDENCE_STATES = frozenset({SOURCE_VERIFIED, USER_CONFIRMED, DERIVED, SUGGESTED})

# States that may take part in a cross-document comparison. Everything else
# is silence or a verdict, and silence is never a rival answer.
COMPARABLE_VALUE_STATES = frozenset({PRESENT, EXPLICIT_NO})

# Sources / confidences the pipeline already writes, mapped to evidence.
_HUMAN_SOURCES = {
    "user_confirmed": "producer",      # Data Consistency picker (producer)
    "producer": "producer",            # recommendation-card answer
    "client_arq": "client",            # client questionnaire
}
_VERIFIED_SOURCES = frozenset({"dec_entry", "policy_doc_text"})
_VERIFIED_CONFIDENCES = frozenset({"deterministic", "filled"})
_DERIVED_SOURCES = frozenset({"derived"})

# "none" is deliberately NOT here. It sits in ``_EMPTY_STRINGS`` (tested first),
# because the extractor emits the string "None" for a null as often as a
# document prints it as an answer - so a bare "None" is silence, never an
# Explicit No (Principle 3: missing does not mean no). It used to be listed in
# both sets, where it was unreachable dead weight (C1-R, 2026-08-24).
_NEGATION_STRINGS = frozenset({
    "no", "n", "false", "nil", "no coverage", "not covered", "no losses",
    "no prior losses", "no claims", "declined",
})
_NOT_APPLICABLE_STRINGS = frozenset({"n/a", "na", "not applicable", "n.a."})
_EMPTY_STRINGS = frozenset({"", "null", "none", "nan", "unknown", "n/a"})


def _unwrap(raw: Any) -> Tuple[Any, dict]:
    if isinstance(raw, dict) and "value" in raw:
        return raw.get("value"), raw
    return raw, {}


def derive_evidence_state(raw: Any) -> Tuple[str, Optional[str]]:
    """(evidence_state, actor) for one stored fact.

    An explicit ``evidence_state`` already on the envelope wins (a derived
    writer labels itself). Otherwise: a human source is ``user_confirmed``
    with its actor; a deterministic / dec-entry-verified value is
    ``source_verified``; anything the model produced without text
    verification is ``suggested`` - including ``ai_high``. That last choice is
    the client's rule, not a judgment of the model: "a Suggested material value
    should not silently become Source Verified", and a high model confidence is
    not a verbatim quote from the document.
    """
    _value, env = _unwrap(raw)
    explicit = str(env.get("evidence_state") or "").strip().lower()
    if explicit in EVIDENCE_STATES:
        actor = env.get("evidence_actor") or _HUMAN_SOURCES.get(str(env.get("source") or ""))
        return explicit, (actor if explicit == USER_CONFIRMED else None)
    source = str(env.get("source") or "").strip().lower()
    confidence = str(env.get("confidence") or "").strip().lower()
    if source in _HUMAN_SOURCES or confidence == "client_arq":
        return USER_CONFIRMED, _HUMAN_SOURCES.get(source, "client")
    if source in _DERIVED_SOURCES:
        return DERIVED, None
    if env.get("verified_in_text") is True or source in _VERIFIED_SOURCES \
            or confidence in _VERIFIED_CONFIDENCES:
        return SOURCE_VERIFIED, None
    return SUGGESTED, None


# ── THE TWO STATES THAT USED TO HAVE NO WRITER (client 1.3) ─────────────────
# Both are computed from signals the pipeline ALREADY produces. Neither makes a
# new judgement, and both only ever fire on a fact that is otherwise EMPTY - a
# value that exists is evidence in its own right and always wins.
REJECTED_FACTS_KEY = "_rejected_facts"


def denied_lines(facts: Optional[dict]) -> frozenset:
    """Canonical coverage families this package explicitly declares absent.

    Reads `coverage_lines` through the line-of-business leaf, which withdraws a
    denial the moment any entry GRANTS the same family - two sources
    disagreeing about whether a coverage exists is a conflict for the producer,
    not a quiet "not applicable" (client 1.7's acceptance criterion).
    """
    if not isinstance(facts, dict):
        return frozenset()
    try:
        from services.lob_canon import denied_families
        return denied_families(facts.get("coverage_lines"))
    except Exception:                                         # noqa: BLE001
        return frozenset()


def _line_of_fact(fact_key: str) -> Optional[str]:
    """The one coverage line this fact belongs to, or None when not unambiguous.

    Delegates to the comparison door's `fact_line`, which intersects the fact's
    own registry `forms` with the table of ACORD LINE sections and returns None
    unless every form agrees on one line. A fact that also reaches ACORD 125 or
    101 is package-level and correctly gets no line, so package identity is
    never marked not-applicable because one section was declined.
    """
    try:
        from services.fact_comparison import _fe as _door
        return _door.fact_line(fact_key)
    except Exception:                                         # noqa: BLE001
        return None


def _is_tristate_fact(fact_key: str) -> bool:
    """Does this fact's extraction contract distinguish "no" from "not found"?

    True only for the keys the schema documents as ``boolean or null``. Read
    from `extraction_service`, which derives the set from the schema string
    itself, so neither side can drift. Fail-closed: if the set cannot be read
    we keep today's behaviour (`not_stated`), because turning silence into a
    "No" is the one direction the client forbids (Principle 3).
    """
    try:
        from services.extraction_service import TRISTATE_BOOLEAN_FACTS
        return fact_key in TRISTATE_BOOLEAN_FACTS
    except Exception:                                         # noqa: BLE001
        return False


def _asserted_absent(fact_key: str, facts: Optional[dict]) -> bool:
    """Does this package carry a flag AFFIRMATIVELY asserting this fact absent?

    The flag lives on `flags`, not `facts`, so it is looked up on the private
    `_flags` copy the pipeline carries alongside them when present. Positive
    evidence only - a missing or false flag is no opinion at all.
    """
    if not isinstance(facts, dict) or not fact_key:
        return False
    try:
        from services.extraction_service import ABSENCE_ASSERTION_FLAGS
        flags = facts.get("_flags")
        if not isinstance(flags, dict):
            return False
        for flag, asserted_keys in ABSENCE_ASSERTION_FLAGS.items():
            if fact_key in asserted_keys and flags.get(flag) is True:
                return True
    except Exception:                                         # noqa: BLE001
        pass
    return False


def _was_rejected(fact_key: str, facts: Optional[dict]) -> bool:
    """True when a value for this fact WAS found and deliberately discarded."""
    if not isinstance(facts, dict):
        return False
    ledger = facts.get(REJECTED_FACTS_KEY)
    return bool(isinstance(ledger, dict) and fact_key in ledger)


def rejection_reason(fact_key: str, facts: Optional[dict]) -> Optional[str]:
    """Why this fact could not be determined, in the words of whoever decided."""
    if not isinstance(facts, dict):
        return None
    ledger = facts.get(REJECTED_FACTS_KEY)
    if isinstance(ledger, dict):
        reason = ledger.get(fact_key)
        return str(reason) if reason else None
    return None


def derive_value_state(fact_key: str, raw: Any, facts: Optional[dict] = None,
                       evidence_state: Optional[str] = None) -> str:
    """Value state for one stored fact, from signals already present.

    * listed in ``facts["_uw_conflicted_keys"]``         -> conflicting
    * envelope flagged ``not_applicable``                -> not_applicable
    * envelope flagged ``rejected_by`` / ``withheld``    -> unable_to_determine
    * empty / null / unknown                              -> not_stated
    * boolean False from extraction                      -> not_stated (B8);
      boolean False a HUMAN supplied                     -> explicit_no
    * a negation string ("none", "no coverage", ...)     -> explicit_no
    * "n/a" style                                         -> not_applicable
    * anything else                                       -> present
    """
    value, env = _unwrap(raw)
    if facts and fact_key in (facts.get("_uw_conflicted_keys") or ()):
        return CONFLICTING
    if env.get("not_applicable") is True:
        return NOT_APPLICABLE
    if env.get("rejected_by") or env.get("withheld") is True:
        return UNABLE_TO_DETERMINE
    # ── A STATE A HUMAN ALREADY RECORDED (C3, 2026-08-25) ───────────────────
    # `answer_semantics.build_fact_envelope` stores an answered absence as
    # ``value: "" + value_state: "explicit_no"`` and an answered inapplicability
    # as ``value_state: "not_applicable"``. This function re-derives from
    # SIGNALS and knew nothing about that key - it looked only for the older
    # ``not_applicable: True`` flag - so it returned `not_stated` for both.
    # Measured: `fact_answered(env)` said True while `value_state_of(...)` said
    # `not_stated` on the SAME envelope. Two modules, two vocabularies, one
    # fact. That mismatch made C3 3.6's "Not Applicable fields are removed from
    # the denominator" unreachable for any human answer, and left
    # `_drop_not_applicable_questions` re-asking questions already answered.
    #
    # Deliberately narrow, so this can only ever REFINE and never override:
    #   * gated on a BLANK value - a fact carrying a real value is untouched;
    #   * only these two states are honoured - a stored `present` / `not_stated`
    #     / `conflicting` is still re-derived from signals as before;
    #   * placed ahead of the package-level derivations below so an explicit
    #     human answer outranks "we could not read this" for the same fact.
    _recorded = env.get("value_state")
    if _recorded in (NOT_APPLICABLE, EXPLICIT_NO) and _is_blank(value):
        return _recorded
    # The two package-level derivations. Ordered NOT APPLICABLE first: if the
    # coverage is not carried at all, the field does not apply, whatever we
    # tried and failed to read for it. Both are gated on an EMPTY value.
    if _is_blank(value):
        line = _line_of_fact(fact_key)
        if line and line in denied_lines(facts):
            return NOT_APPLICABLE
        if _was_rejected(fact_key, facts):
            return UNABLE_TO_DETERMINE
    # ── EXPLICIT NO FROM A DOCUMENT (client 1.3) ────────────────────────────
    # "No prior losses" is the client's own first example of an Explicit No,
    # and the extraction schema already asks for it precisely - but as a
    # separate ASSERTION flag rather than as a value on the fact, so the fact
    # itself read `not_stated` and the distinction the client asked for was
    # unreachable from any document. Positive evidence only: the flag is true
    # ONLY when the document affirmatively states there were none, and a fact
    # that HAS a value always wins (this runs on blanks alone).
    if _is_blank(value) and _asserted_absent(fact_key, facts):
        return EXPLICIT_NO
    if value is None:
        return NOT_STATED
    if isinstance(value, bool):
        if value:
            return PRESENT
        es = evidence_state or derive_evidence_state(raw)[0]
        if es == USER_CONFIRMED:
            return EXPLICIT_NO
        # A TRI-STATE fact is one the extraction contract tells the model to
        # answer `null` on when the document is silent - so a `false` is the
        # document saying no, not our failure to find an answer. Every other
        # boolean stays `not_stated`: that is B8, where a certificate which
        # never mentioned subcontractors produced `false` and manufactured a
        # conflict plus an 85 cap.
        return EXPLICIT_NO if _is_tristate_fact(fact_key) else NOT_STATED
    if isinstance(value, (list, dict)):
        return PRESENT if value else NOT_STATED
    text = str(value).strip().lower()
    if text in _NOT_APPLICABLE_STRINGS:
        return NOT_APPLICABLE
    if text in _EMPTY_STRINGS:
        return NOT_STATED
    if text in _NEGATION_STRINGS:
        return EXPLICIT_NO
    return PRESENT


def derive_states(fact_key: str, raw: Any, facts: Optional[dict] = None) -> Dict[str, Any]:
    """Both axes for one fact, as the keys the envelope carries."""
    es, actor = derive_evidence_state(raw)
    vs = derive_value_state(fact_key, raw, facts, es)
    out: Dict[str, Any] = {"value_state": vs, "evidence_state": es}
    if actor:
        out["evidence_actor"] = actor
    return out


def display_state(value_state: str, evidence_state: str) -> str:
    """The 125 doc's four-word projection the producer sees.

    VERIFIED        present/explicit_no AND source_verified/derived
    CONFIRMED       present/explicit_no AND user_confirmed
    NOT APPLICABLE  not_applicable
    UNRESOLVED      everything else - not_stated, unable_to_determine,
                    conflicting, and a value that is merely suggested
    """
    if value_state == NOT_APPLICABLE:
        return "NOT APPLICABLE"
    if value_state in COMPARABLE_VALUE_STATES:
        if evidence_state == USER_CONFIRMED:
            return "CONFIRMED"
        if evidence_state in (SOURCE_VERIFIED, DERIVED):
            return "VERIFIED"
    return "UNRESOLVED"


def is_comparable(fact_key: str, raw: Any, facts: Optional[dict] = None) -> bool:
    """May this stored value take part in a cross-document comparison?"""
    return derive_value_state(fact_key, raw, facts) in COMPARABLE_VALUE_STATES


def annotate_fact_states(facts: dict, flags: Optional[dict] = None) -> dict:
    """Write ``value_state`` / ``evidence_state`` onto every envelope in place.

    Additive and idempotent. Bare scalars (legacy shape) are left untouched -
    wrapping them would change the shape every consumer reads. Private keys
    (``_``-prefixed) are skipped. Returns ``facts`` for chaining.
    """
    if not isinstance(facts, dict):
        return facts
    # The absence-assertion flags live on `flags`, not `facts`. Stashed for the
    # duration of the pass rather than persisted, so nothing downstream gains a
    # second copy of the flags to drift from.
    _had = "_flags" in facts
    _prev = facts.get("_flags")
    if isinstance(flags, dict):
        facts["_flags"] = flags
    try:
        for key, raw in list(facts.items()):
            if not key or key.startswith("_"):
                continue
            if isinstance(raw, dict) and "value" in raw:
                raw.update(derive_states(key, raw, facts))
    finally:
        if isinstance(flags, dict):
            if _had:
                facts["_flags"] = _prev
            else:
                facts.pop("_flags", None)
    return facts

def human_provenance_facts(facts: Optional[dict]) -> Dict[str, dict]:
    """Every fact envelope a HUMAN supplied or confirmed, keyed by fact key.

    Used to carry human answers across a pipeline re-run (V1 C1-D, Q7):
    ``merge_facts`` rebuilds facts from the documents alone, so a producer or
    client value for a field the documents never mention was destroyed by every
    re-run. Private keys and bare scalars are skipped - a bare scalar carries no
    provenance, so there is nothing to assert about who supplied it.
    """
    out: Dict[str, dict] = {}
    if not isinstance(facts, dict):
        return out
    for key, raw in facts.items():
        if not key or key.startswith("_"):
            continue
        if not (isinstance(raw, dict) and "value" in raw):
            continue
        value = raw.get("value")
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if derive_evidence_state(raw)[0] == USER_CONFIRMED:
            out[key] = dict(raw)
    return out


def _is_blank(value: Any) -> bool:
    """Empty for state purposes. A bare ``False`` is NOT blank - it is an
    answer, and which answer it is depends on who supplied it (see B8)."""
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (list, dict)):
        return not value
    return str(value).strip().lower() in _EMPTY_STRINGS


def value_state_of(facts: Optional[dict], fact_key: str) -> str:
    """Value state for ``fact_key`` whether or not ``facts`` carries it.

    THE POINT OF THIS FUNCTION IS THE ABSENT CASE. "Not applicable" and "unable
    to determine" are answers about fields we do NOT have a value for, so a
    state that can only be read off an existing envelope can never express
    either one. Callers deciding whether to ASK about a field - the
    questionnaire, the gap list, an audit export - must use this.
    """
    if not isinstance(facts, dict) or not fact_key:
        return NOT_STATED
    raw = facts.get(fact_key)
    if raw is None and fact_key not in facts:
        raw = None
    return derive_value_state(fact_key, raw, facts)


def is_not_applicable(facts: Optional[dict], fact_key: str) -> bool:
    """True when this package's own documents say the field does not apply.

    Positive evidence only: a package with no ``coverage_lines``, an unmapped
    line name, or any entry granting the same family all return False.
    """
    return value_state_of(facts, fact_key) == NOT_APPLICABLE
