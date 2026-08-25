"""answer_semantics.py - what does a human's answer MEAN?

THE ONE DOOR for interpreting anything a person types into Primble: a producer
answering a recommendation card, resolving a hard stop or warning inline, or a
client answering the questionnaire. Every one of those paths used to store the
raw string as the fact's VALUE, which conflated three different meanings:

    "Travelers"              a VALUE
    "None" / "never had one" an ABSENCE - a real answer, and the answer is none
    "TBD" / "don't know"     a NON-ANSWER - no information at all

Measured 2026-08-24: typing "N/A" into every Tier-2 field scored 100, exactly
as if the submission were fully answered, because the only test anywhere was
`bool(value)` - is the string non-empty. Meanwhile a legitimate "None" scored
as a GAP, because "none" sits in `_EMPTY_VALUES`. Both directions wrong, from
one root cause: *"what is the value?"* and *"did they answer?"* were the same
question.

BRENT'S RULING 2026-08-24 settles which way each falls: *"we can't treat 'N/A'
as '0'. These are not the same. 'No known losses' is a legitimate answer ...
that category shouldn't be penalized."* So an ABSENCE is an ANSWER (no penalty,
never re-asked) while a NON-ANSWER is missing information (not stored, asked
again).

WHY THIS IS NOT A LIST OF ACCEPTED ANSWERS
------------------------------------------
The tables below describe **how English expresses four ideas**, and they are
applied identically to all 175 facts. Adding a new fact needs no new entry
here - that is the test of whether this generalises. What a given field will
ACCEPT comes from the field's own declaration in `FACT_REGISTRY` (its validator
and format hint), never from a per-field synonym list:

  1. NEGATIVE EXISTENCE   none / nil / zero / never / without / no <X>
  2. UNCERTAINTY          don't know / unsure / TBD / will confirm / ?
  3. INAPPLICABILITY      n/a / not applicable / doesn't apply
  4. AFFIRMATION-DENIAL   yes / correct / confirmed  vs  no / false

PRECEDENCE IS WHERE MEANING IS ACTUALLY JUDGED - a keyword scan cannot do this:
  * uncertainty BEFORE negation      "no idea" contains "no" but means unknown
  * a parseable value BEFORE negation "0" employees is a VALUE, not an absence
  * negation needs SCOPE, not a word  carrier "Nationwide" is never "no"
  * a long sentence needs an explicit existential negation, so a descriptive
    answer that merely contains "not" stays a value

DELIBERATELY NO LLM. Owner's call 2026-08-24, and the reasons that matter are
not token cost (a classification call is ~0.03% of a submission's LLM spend):
an interactive click must not wait on a round trip, and a scoring input must
not change between two runs of the same answer. `unresolved_answers()` logs
every answer this module could not read, so coverage is measured rather than
assumed - if that log fills with real phrasings we extend the rules with
evidence.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, NamedTuple, Optional

logger = logging.getLogger(__name__)

# ── Intents ──────────────────────────────────────────────────────────────────
VALUE = "value"                 # a real value was given
ABSENCE = "absence"             # answered: there is none
NOT_APPLICABLE = "not_applicable"   # answered: does not apply to this account
UNKNOWN = "unknown"             # not answered: no information

# Value states (mirrors services.fact_state's vocabulary - client 1.3).
STATE_PRESENT = "present"
STATE_EXPLICIT_NO = "explicit_no"
STATE_NOT_APPLICABLE = "not_applicable"
STATE_NOT_STATED = "not_stated"

_INTENT_TO_STATE = {
    VALUE: STATE_PRESENT,
    ABSENCE: STATE_EXPLICIT_NO,
    NOT_APPLICABLE: STATE_NOT_APPLICABLE,
    UNKNOWN: STATE_NOT_STATED,
}


class Interpretation(NamedTuple):
    """What the person meant, and what to do about it."""
    intent: str
    value: str            # canonical value to store ("" for absence/unknown)
    value_state: str
    accepted: bool        # False = do not write this to facts
    message: str          # producer-facing text when not accepted
    reason: str           # which rule decided - for the audit trail and logs
    answer_text: str      # exactly what the person typed, always preserved

    @property
    def answered(self) -> bool:
        """True when the person gave a real answer - including 'there is
        none'. This is the ANSWERED question, never the HAS-A-VALUE question."""
        return self.intent in (VALUE, ABSENCE, NOT_APPLICABLE)


# ── 1. Uncertainty: no information given. Checked FIRST ("no idea") ──────────
_UNCERTAIN_RE = re.compile(
    r"(?:^|\b)(?:"
    r"do(?:n'?t| not) know|dunno|not sure|unsure|uncertain|unclear|unknown|"
    r"no idea|can'?t say|cannot say|can'?t tell|need to (?:check|confirm|ask|find)|"
    r"will (?:check|confirm|find out|get|provide|send|follow ?up|revert)|"
    r"to be (?:determined|confirmed|advised|provided)|t\.?b\.?[dcap]\.?|"
    r"waiting|awaiting|chasing|follow(?:ing)? up|ask(?:ing)? the (?:client|insured)|"
    r"not (?:yet )?(?:known|available|received|confirmed|provided)|"
    r"pending (?:from|with)|no answer|not answered|skip|later"
    r")(?:\b|$)", re.I)

# A lone question mark, or an answer that is only punctuation, says nothing.
_NON_ANSWER_ONLY = re.compile(r"^[\s\?\.\-–—_/\\*]+$")


# ── 2. Inapplicability: answered, but the question does not apply ────────────
_NA_TOKENS = frozenset({
    "n/a", "na", "n.a.", "n/a.", "not applicable", "non applicable",
    "does not apply", "doesnt apply", "doesn't apply", "not relevant",
    "irrelevant", "not required", "no longer applicable",
})
_NA_RE = re.compile(
    r"\b(?:n\s*/\s*a|not applicable|does(?:\s+not|n'?t) apply|not relevant)\b", re.I)


# ── 3. Negative existence: answered, and the answer is "there is none" ───────
# Short-answer tokens: the WHOLE answer is a negation.
_ABSENCE_TOKENS = frozenset({
    "none", "no", "nil", "nada", "nothing", "zero", "0", "never", "n",
    "none at all", "none known", "none reported", "none to report",
    "nothing to report", "no ne",
})
# Existential negation ANYWHERE in a longer sentence. Requires the negation to
# govern existence ("there is no X", "we have never had X"), so a descriptive
# answer that merely contains "not" is untouched.
_ABSENCE_PHRASE_RE = re.compile(
    r"\b(?:"
    r"(?:there (?:is|are|were|was)|we|they|applicant|insured|company|business)?\s*"
    r"(?:have|has|had|do|does|did)?\s*(?:not|n'?t|never)\s+(?:have|had|carry|carried|"
    r"maintain|maintained|purchase[d]?|been|owned?)|"
    r"no (?:prior|previous|current|existing|known|reported|such|other)?\s*"
    r"(?:coverage|carrier|policy|policies|claims?|losses|loss|insurance|history|"
    r"record|records|employees|vehicles|locations|subcontractors|operations)|"
    r"none (?:of|on|in|at|for|available|exist|existing|found|on file)|"
    r"without (?:any )?(?:coverage|insurance|claims?|losses)|"
    r"first[- ]time (?:buyer|buying|purchase)|previously uninsured|"
    r"never (?:insured|carried|had|been insured)"
    r")\b", re.I)


# ── 4. Affirmation / denial ──────────────────────────────────────────────────
_AFFIRM_TOKENS = frozenset({
    "yes", "y", "yeah", "yep", "yup", "true", "correct", "confirmed", "confirm",
    "affirmative", "agreed", "right", "ok", "okay", "done", "applies",
})
_DENY_TOKENS = frozenset({
    "no", "n", "nope", "nah", "false", "incorrect", "negative", "denied",
})


# ── Number words - the language's inventory, not a per-field list ────────────
_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALE_WORDS = {"hundred": 100, "thousand": 1_000, "million": 1_000_000,
                "billion": 1_000_000_000}
# Magnitude suffixes people type on money: 2M, 2mm, 1.5k, 3bn
_MAGNITUDE_SUFFIX = {"k": 1_000, "m": 1_000_000, "mm": 1_000_000,
                     "b": 1_000_000_000, "bn": 1_000_000_000}

# Words that soften a number without changing it ("about 12", "approx 5").
# Symbol hedges are stripped separately: "~" and "+/-" are not word characters,
# so a \b-anchored alternation can never match them.
_HEDGE_RE = re.compile(
    r"\b(?:about|approx(?:imately)?|around|roughly|circa|est(?:imated)?|"
    r"give or take|over|under|at least|more than|less than|up to)\b", re.I)
_HEDGE_SYMBOL_RE = re.compile(r"[~≈]|\+/-|\+/−")


def _normalize(text: Any) -> str:
    s = str(text or "").strip().lower()
    s = s.replace("’", "'").replace("‘", "'")
    s = re.sub(r"\s+", " ", s)
    return s


def _strip_edges(s: str) -> str:
    return s.strip(" .!,;:-–—\"'()")


def words_to_number(text: str) -> Optional[float]:
    """Parse a number written in words or shorthand. Language-level, so it
    serves every numeric fact: "five" -> 5, "two million" -> 2000000,
    "1.5k" -> 1500, "$2M" -> 2000000, "about 12" -> 12."""
    if not text:
        return None
    s = _HEDGE_SYMBOL_RE.sub(" ", _normalize(text))
    s = _HEDGE_RE.sub(" ", s)
    s = s.replace("$", " ").replace(",", "")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None

    # "2m" / "1.5k" / "3 bn" / "2 million"
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*([a-z]{1,7})?", s)
    if m:
        num = float(m.group(1))
        suf = (m.group(2) or "").strip()
        if not suf:
            return num
        if suf in _MAGNITUDE_SUFFIX:
            return num * _MAGNITUDE_SUFFIX[suf]
        if suf in _SCALE_WORDS:
            return num * _SCALE_WORDS[suf]
        return num          # a trailing unit word ("12 employees", "5 years")
    # Leading number with trailing PROSE: "12 employees at 3 locations".
    # The remainder must be whitespace-then-letters. Requiring that is what
    # keeps a structurally malformed number out: "12.34.56" leaves ".56", which
    # is not prose, so it is refused rather than silently becoming 12.
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s+([a-z].*)$", s)
    if m:
        num = float(m.group(1))
        suf = m.group(2).split()[0]
        if suf in _MAGNITUDE_SUFFIX:
            return num * _MAGNITUDE_SUFFIX[suf]
        if suf in _SCALE_WORDS:
            return num * _SCALE_WORDS[suf]
        return num

    # Written out: "twenty five", "two million", "one hundred fifty"
    tokens = [t for t in re.split(r"[\s-]+", s) if t and t != "and"]
    if not tokens or not all(t in _NUM_WORDS or t in _SCALE_WORDS for t in tokens):
        return None
    total, current = 0.0, 0.0
    for t in tokens:
        if t in _NUM_WORDS:
            current += _NUM_WORDS[t]
        else:
            scale = _SCALE_WORDS[t]
            if scale >= 1000:
                total += (current or 1) * scale
                current = 0.0
            else:
                current = (current or 1) * scale
    return total + current


def _fmt_number(n: float, as_int: bool) -> str:
    if as_int or float(n).is_integer():
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


# ── Field typing, taken from the fact's OWN declaration ──────────────────────

def _registry_entry(fact_key: str) -> dict:
    try:
        from services.fact_registry import FACT_REGISTRY
        return FACT_REGISTRY.get(fact_key) or {}
    except Exception:                                         # noqa: BLE001
        return {}


def _declared_kind(fact_key: str, entry: dict) -> Optional[str]:
    """What shape this fact wants - read from its own declaration, never from a
    hand-kept list of field names here.

    `arq_service._FIELD_INPUT_TYPE` is the authoritative table (it already
    drives the questionnaire's input widgets), so it is consulted FIRST and
    this function only falls back to the registry's format hint and the key's
    own naming for facts that table does not cover.
    """
    key = (fact_key or "").lower()
    try:
        from services.arq_service import _FIELD_INPUT_TYPE
        declared = _FIELD_INPUT_TYPE.get(fact_key)
        if declared:
            # "code" is an IDENTIFIER (FEIN, NAICS, SIC): its digits are a
            # string, not a quantity. Coercing "84-2210987" as a number yields
            # 84 and destroys the value - so codes are never numeric-coerced.
            return {"number": "integer", "currency": "currency",
                    "date": "date", "code": "code"}.get(declared)
    except Exception:                                         # noqa: BLE001
        pass
    hint = str(entry.get("format_hint") or "").lower()
    if any(t in key for t in ("_code", "fein", "policy_number", "vin", "zip",
                              "postal", "phone", "naic", "license")):
        return "code"
    if "date" in hint or key.endswith("_date") or key.endswith("_dates"):
        return "date"
    if "percent" in hint or "%" in hint or "percent" in key or "pct" in key:
        return "percent"
    if "dollar" in hint or "amount" in hint or any(
            t in key for t in ("limit", "value", "revenue", "payroll", "premium",
                               "deductible", "sir", "incurred", "paid", "cost",
                               "sales", "income")):
        return "currency"
    if "whole number" in hint or "digit" in hint or any(
            t in key for t in ("count", "num_", "_num", "year_built", "roof_year",
                               "years_", "_years", "employees")):
        return "integer"
    return None


# NEGATIVE-POLARITY FACTS: the fact's own NAME asserts an absence, so "none"
# is the AFFIRMATIVE answer, not an empty one. `loss_history_no_prior_losses_
# indicator` means "no prior losses = true" - answering "None" fills it rather
# than emptying it. Derived from the key's shape, not a maintained list, so a
# future `no_known_subcontractors` behaves correctly the day it is added.
_NEGATIVE_POLARITY_RE = re.compile(
    r"(?:^|_)(?:no|not|never|without)_(?:prior|known|reported|previous|"
    r"outstanding|open|pending|current)?_?", re.I)


def is_absence_affirmative(fact_key: str) -> bool:
    """True when answering "there is none" FILLS this fact rather than
    emptying it - because the fact itself is phrased as an absence."""
    k = (fact_key or "").lower()
    return bool(_NEGATIVE_POLARITY_RE.search(k)) and any(
        t in k for t in ("loss", "claim", "prior", "known", "subcontract",
                         "operation", "coverage", "exclusion", "violation"))


def _coerce_typed(kind: Optional[str], text: str) -> Optional[str]:
    """Canonicalize a value into the shape downstream code already reads.
    Returns None when the text is not a value of that kind."""
    if not kind or kind == "code":
        # An identifier is a STRING of characters, not a quantity. Its own
        # registry validator judges it; this must never reshape it.
        return None
    if kind == "date":
        try:
            from services.normalization import normalize_date
            iso = normalize_date(text)
            if iso:
                y, m, d = iso.split("-")
                return f"{m}/{d}/{y}"
        except Exception:                                     # noqa: BLE001
            pass
        return None
    n = words_to_number(text)
    if n is None:
        return None
    if kind == "percent":
        return _fmt_number(n, as_int=False)
    if kind == "integer":
        return _fmt_number(n, as_int=True)
    if kind == "currency":
        return _fmt_number(n, as_int=True)
    return None


# ── The one entry point ──────────────────────────────────────────────────────

_UNREADABLE: List[dict] = []          # coverage evidence, see unresolved_answers()


def interpret_answer(fact_key: str, answer: Any,
                     entry: Optional[dict] = None) -> Interpretation:
    """Interpret one human answer for one fact. Pure and deterministic."""
    raw = str(answer or "")
    text = _normalize(raw)
    stripped = _strip_edges(text)
    entry = entry if entry is not None else _registry_entry(fact_key)

    def out(intent, value="", reason="", message=""):
        return Interpretation(
            intent=intent, value=value, value_state=_INTENT_TO_STATE[intent],
            accepted=(intent != UNKNOWN), message=message, reason=reason,
            answer_text=raw.strip(),
        )

    _ask_again = ("That reads as 'not known yet' rather than an answer. Leave it "
                  "blank and we will keep asking, or enter the value once you "
                  "have it. If there genuinely is none, answer \"None\".")

    # 0. Nothing typed, or punctuation only.
    if not stripped or _NON_ANSWER_ONLY.match(raw.strip() or " "):
        return out(UNKNOWN, reason="empty", message=_ask_again)

    # 0b. AN OPTION CHOSEN FROM THE FIELD'S OWN LIST IS, BY DEFINITION, A VALUE.
    #     It must never be re-read as prose: "No - all owners and officers are
    #     included" is a meaningful answer, not an absence, and "Not stated -
    #     underwriter review recommended" is a deliberate choice, not a
    #     non-answer. Matched case-insensitively and returned in the
    #     catalogue's exact wording, so the stored value is always canonical.
    try:
        from services.answer_options import options_for
        for opt in (options_for(fact_key) or ()):
            if stripped == _strip_edges(_normalize(opt)):
                return out(VALUE, value=opt, reason="declared_option")
    except Exception:                                         # noqa: BLE001
        pass

    # 1. UNCERTAINTY first - "no idea" contains "no" but means unknown.
    if _UNCERTAIN_RE.search(text):
        return out(UNKNOWN, reason="uncertainty", message=_ask_again)

    kind = _declared_kind(fact_key, entry)

    # 2. A parseable value of the field's declared type beats negation, so a
    #    count of "0" stays a VALUE rather than becoming an absence.
    coerced = _coerce_typed(kind, stripped)
    if coerced is not None:
        return out(VALUE, value=coerced, reason=f"typed:{kind}")

    # 3. INAPPLICABILITY - a real answer, per Brent: N/A is not zero.
    if stripped in _NA_TOKENS or _NA_RE.search(text):
        return out(NOT_APPLICABLE, reason="not_applicable")

    # 4. NEGATIVE EXISTENCE. Short answers may be a bare token; longer ones
    #    need an explicit existential negation so a descriptive sentence that
    #    merely contains "not" is left alone as a value.
    words = stripped.split()
    _absent = (
        (stripped in _ABSENCE_TOKENS and not (kind and stripped in ("0", "zero")))
        or (len(words) <= 5 and any(w in _ABSENCE_TOKENS for w in words[:2])
            and not _AFFIRM_TOKENS.intersection(words[:1]))
        or bool(_ABSENCE_PHRASE_RE.search(text))
    )
    if _absent:
        # On a negative-polarity fact ("no prior losses"), "none" is the
        # AFFIRMATIVE answer - it fills the fact. The person's own words are
        # kept as the value so the readers that already parse this family
        # (`_attested_true`, `new_venture_answer`) keep working unchanged, and
        # a bare "No" keeps the legacy meaning those readers depend on.
        if is_absence_affirmative(fact_key):
            return out(VALUE, value=(raw.strip() or "None"),
                       reason="absence:affirms_negative_fact")
        # A bare "no"/"n" on any other fact means "there is none".
        return out(ABSENCE, reason="absence")

    # 5. AFFIRMATION / DENIAL - stored as the canonical Yes/No the ACORD
    #    indicator fields and `_attested_true` already read.
    if stripped in _AFFIRM_TOKENS:
        return out(VALUE, value="Yes", reason="affirmation")
    if stripped in _DENY_TOKENS:
        return out(VALUE, value="No", reason="denial")

    # 6a. A monetary box legitimately holds a descriptive convention -
    #     "Statutory", "Waived", "Not covered", "See schedule". This mirrors
    #     `pdf_service._rejects_declared_type`, which is permissive by default:
    #     an amount answer with no digits at all is real data, not garbage.
    #     Only an answer that HAS digits and still will not parse is refused.
    #     Applies to percent-typed boxes too: a deductible whose format hint
    #     offers "$25,000 or 2%" is the same kind of box and holds the same
    #     conventions ("NOT COVERED DEDUCTIBLE - EARTHQUAKE COVERAGE").
    if kind in ("currency", "percent") and not any(ch.isdigit() for ch in stripped):
        return out(VALUE, value=raw.strip(), reason="descriptive_amount")

    # 6b. A typed field that reached here was NOT readable as its own type.
    #     Refuse it rather than storing text a scorer will silently read as 0 -
    #     and record it, so coverage is measured instead of assumed.
    if kind in ("currency", "integer", "percent", "date"):
        _record_unreadable(fact_key, raw, kind)
        return out(UNKNOWN, reason=f"unreadable:{kind}", message=(
            f"That does not read as a {'date' if kind == 'date' else 'number'} "
            f"for this field. Enter it as "
            f"{'MM/DD/YYYY' if kind == 'date' else 'digits (e.g. 12 or $50,000)'}"
            ", or answer \"None\" if there is none."))

    # 7. Ordinary free text is the value.
    return out(VALUE, value=raw.strip(), reason="free_text")


def _record_unreadable(fact_key: str, raw: str, kind: str) -> None:
    """Coverage evidence. The owner declined an LLM layer on cost/latency
    grounds; this is what keeps that decision honest - every answer the
    deterministic rules could not read is logged, so the gap is measured."""
    _UNREADABLE.append({"fact": fact_key, "answer": raw[:120], "kind": kind})
    del _UNREADABLE[:-200]
    logger.info("answer_semantics: could not read %r as %s for %s - "
                "producer asked to rephrase", raw[:80], kind, fact_key)


def unresolved_answers() -> List[dict]:
    """Recent answers the deterministic rules could not interpret."""
    return list(_UNREADABLE)


# ── The two questions, finally separated ─────────────────────────────────────

def fact_answered(raw: Any) -> bool:
    """DID THE PERSON ANSWER? - which is NOT "is there a value".

    An absence ("None") and an inapplicability ("N/A") are ANSWERS and must
    never be scored as gaps (Brent 2026-08-24). A non-answer is not stored at
    all, so it can never reach here as an answer.

    Consumers asking "what is the value?" keep reading the value, which is
    empty for an absence - so `has_carrier`-style checks stay correct.
    """
    if isinstance(raw, dict):
        if raw.get("value_state") in (STATE_EXPLICIT_NO, STATE_NOT_APPLICABLE):
            return True
        raw = raw.get("value")
    if raw is None:
        return False
    if isinstance(raw, (list, dict)):
        return len(raw) > 0
    return str(raw).strip().lower() not in ("", "null", "none", "[]", "{}")


def build_fact_envelope(fact_key: str, interp: Interpretation,
                        source: str, confidence: str) -> Dict[str, Any]:
    """The fact envelope an accepted answer becomes. `answer_text` preserves
    what the person actually typed, so the audit trail never loses their own
    words even when the stored value is canonicalized or empty."""
    env: Dict[str, Any] = {
        "value": interp.value,
        "confidence": confidence,
        "source": source,
        "value_state": interp.value_state,
    }
    if interp.answer_text and interp.answer_text != interp.value:
        env["answer_text"] = interp.answer_text
    return env
