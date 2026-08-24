"""fact_equivalence.py - is this ONE fact written two ways, or two facts?

THE PROBLEM THIS SOLVES (client 2026-08-17: "Primble should escalate judgment,
not formatting"). Three places in the codebase decide whether two values
conflict - ``underwriting_consistency.assess_underwriting_consistency`` (the
Data Consistency picker), ``sqs_service.check_doc_consistency`` (the identity
hard stops) and ``extraction_service.detect_source_conflicts`` (the catch-all
warning). Each carried its own private, hand-maintained idea of which fields it
understands: 16 fields, ~9 fields, and none, against 173 real facts. Everything
outside those lists was compared as raw text, so a dec page's ``$2,000,000`` and
a certificate's ``$2,000,000 General Aggregate`` became a question for a human.

Measured before writing a line: 42 realistic "same fact, two printings" pairs
were run through the live comparator and **24 came back as conflicts**, across
EIGHT shape families. The client had reported two of them.

    money + label      $2,000,000        vs $2,000,000 General Aggregate
    fragment           <full address>    vs Denver, Colorado
    contact format     303-996-7800      vs 3039967800
    code + description 91580             vs 91580 Contractors - Executive Supervisors
    yes/no wording     Yes               vs Y
    number + unit      50                vs 50 miles
    abbreviation       CO                vs Colorado
    identifier print   6C7-40-02---26    vs 6 C 7 - 4 0 - 0 2---26

ONE RULE, not eight patches: **compare a value the way its own declared type
should be compared.** ``fact_registry.FACT_REGISTRY`` already declares a type
for every fact (51 currency, 10 date, 10 integer, 5 percent, ...), and
``normalization`` already declares the identity categories. Neither was ever
consulted by the conflict layer. A fact added tomorrow is covered the day it is
added, because its registry entry already carries the type.

── WHY THIS IS A FILTER AND NOT A NEW COMPARATOR ────────────────────────────
Callers run their existing grouping FIRST and then pass the resulting groups
through :func:`merge_equivalent_groups`. Three properties follow structurally
rather than by care:

1. **It can only ever REMOVE a conflict.** There is no code path that splits a
   group. Manufacturing new noise is impossible, so the change is
   one-directional and cannot regress into the failure mode it exists to fix.
2. **Failure is a no-op.** Every public entry point is wrapped; an exception
   leaves the caller's own grouping exactly as it was.
3. **It never changes a stamped value.** The merge still decides what goes on
   the form. This decides only what we ASK A HUMAN about.

REJECTED, recorded so nobody rebuilds it: changing ``normalization.
normalize_value`` itself. It is shared with ``field_qa``, the cross-chunk merge
and document clustering, whose equivalence semantics are deliberately DIFFERENT
- Round 10 fix 46 exists precisely because one coarse normalizer was serving
consumers that needed different answers ("EMC Property & Casualty" and
"Employers Mutual Casualty" must collapse for clustering and must NOT collapse
for the conflict picker).

── WHAT IT DELIBERATELY WILL NOT DO ─────────────────────────────────────────
It never decides that two DIFFERENT numbers are the same, at any distance. No
tolerance band, no "close enough", no fuzzy string ratio. The client's praised
$3,000,000-vs-$1,000,000 umbrella conflict must survive every rule in this file,
and ``test_the_umbrella_conflict_survives_every_rule`` is the gate on the whole
change.

It also will not judge whether a value is CORRECT - only whether two values are
the same thing. Correctness stays with the human, which is the client's own
principle.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Verdicts. Deliberately three, not a boolean: "cannot compare" is a real and
# distinct answer (two remarks paragraphs are neither the same value nor rival
# answers to one question), and collapsing it into either boolean produces a
# defect - False manufactures the client's complaint, True hides real data.
SAME = "same"
DIFFERENT = "different"
INCOMPARABLE = "incomparable"


# ── Value kinds ──────────────────────────────────────────────────────────────
# Derived, never listed. The order of resolution matters and is asserted by
# test_value_kind_resolution_order.
KIND_MONEY = "money"
KIND_COUNT = "count"
KIND_PERCENT = "percent"
KIND_DATE = "date"
KIND_PHONE = "phone"
KIND_EMAIL = "email"
KIND_URL = "url"
KIND_FEIN = "fein"
KIND_YESNO = "yesno"
KIND_CODE = "code"
KIND_STATE = "state"
KIND_IDENTIFIER = "identifier"
KIND_ADDRESS = "address"
KIND_NAME = "name"
KIND_NARRATIVE = "narrative"
KIND_TEXT = "text"

# Registry validator name -> kind. The registry names these functions, so this
# maps a declaration we already maintain rather than inventing a second one.
_VALIDATOR_KIND = {
    "_is_currency":     KIND_MONEY,
    "_is_positive_int": KIND_COUNT,
    "_is_percent":      KIND_PERCENT,
    "_is_date":         KIND_DATE,
    "_is_phone":        KIND_PHONE,
    "_is_email":        KIND_EMAIL,
    "_is_url":          KIND_URL,
    "_is_fein":         KIND_FEIN,
}

# Key-shape fallback for facts whose registry validator is a lambda (36 of them)
# or absent (51). Whole-token matching, never substring, so "sir" cannot fire
# inside another word - the same discipline underwriting_consistency.
# _RETENTION_MONEY_TOKENS uses.
_MONEY_TOKENS = frozenset({
    "limit", "limits", "amount", "premium", "premiums", "deductible",
    "deductibles", "value", "sir", "retention", "payroll", "revenue", "sales",
    "cost", "receipts", "attachment",
})
# "number" is DELIBERATELY absent: `policy_number` and `certificate_number` are
# identifiers, not counts, and having it here classified them as counts (found
# by the sweep - the OCR letter-spacing and short-printing pairs both failed).
# A real count names WHAT is counted.
_COUNT_TOKENS = frozenset({"count", "employees", "units", "stories",
                           "vehicles", "drivers", "claims", "years"})
_CODE_TOKENS = frozenset({"code", "codes", "naics", "sic", "class", "symbol",
                          "symbols"})
# STRONG: the token itself names an identifier, so it decides before the weaker
# money/count shapes. WEAK: only meaningful once nothing else has claimed it.
# STRONG means the token names an identifier ON ITS OWN. "policy" does not -
# it is a QUALIFIER, and it was outranking every money token because the strong
# set is tested before `_MONEY_TOKENS`. So `total_policy_premium` was classed
# `identifier`, which (a) printed "the documents carry different identifiers"
# about a dollar amount on the live Run B screen, and (b) denied the field the
# component rule that `is_component_of` exists for - a LINE premium being part
# of the PACKAGE premium is its own headline example, and
# `test_a_line_premium_is_a_component_of_the_package_total` had been passing
# only because nothing gated the rule by kind.
#
# Demoted to WEAK, which is tested AFTER money: `policy_number`,
# `prior_policy_number`, `policy_form_type` and `policy_term_months` still
# resolve to `identifier` (no money token), while `total_policy_premium`,
# `policy_limit`, `policy_deductible` and the per-line `*_policy_premium` keys
# resolve to `money`. Swept: 7 keys corrected, 0 identifiers broken.
_IDENTIFIER_TOKENS_STRONG = frozenset({"identifier", "vin", "license",
                                       "naic", "certificate"})
_IDENTIFIER_TOKENS_WEAK = frozenset({"number", "id", "no", "policy"})
_PHONE_TOKENS = frozenset({"phone", "fax", "telephone", "mobile", "cell"})
_NARRATIVE_TOKENS = frozenset({
    "description", "descriptions", "remarks", "narrative", "notes", "note",
    "comment", "comments", "explanation", "wording", "operations", "text",
})

# Free-text CHARACTERISATIONS of the business that the schema defines no
# enumeration for. The model returns whatever phrasing each document used, so
# two documents produce two phrasings of one trade - the client's "levels of
# detail", verbatim.
#
# LIVE RUN A: "Licensed electrical and roofing contractor" (certificate) against
# "Commercial General Contractor - Roofing and Electrical" (dec page) opened a
# Data Consistency conflict. Both describe one business, and picking one string
# fixes nothing - the SAME package's `operations_description` holds
# "Licensed electrical and roofing contractor. Commercial and residential
# installation..." and already folds correctly, because it is narrative.
#
# DELIBERATELY NOT ROUTED THROUGH KIND_NARRATIVE. A true narrative field
# (`operations_description`, `additional_remarks_text`) exits `same_fact`
# unconditionally at the top, before containment or truncation ever run - the
# right default for an actual paragraph, where a coincidental substring match
# is a real risk. `contractor_type` holds a short PHRASE, not a paragraph, and
# it still needs those checks: reclassifying it as KIND_NARRATIVE was tried
# first and broke `test_equivalence_families[contractor_type-...]` - an OCR
# truncation ("Commercia" / "Commercial roofing contractor") stopped being
# recognised as one value, because the narrative branch short-circuits before
# `_is_midword_truncation` ever runs.
#
# So this set is consulted only once ALL of `same_fact`'s ordinary machinery -
# exact match, containment, truncation, the WS-2 synonym table - has failed to
# find SAME. At that point a normal field would return DIFFERENT; a field in
# this set returns INCOMPARABLE instead, because "two different phrasings we
# could not otherwise reconcile" is not evidence they are different, only that
# neither is a strict rewording of the other.
#
# AN EXPLICIT LIST, NOT A SHAPE TEST, and that is deliberate. 39 facts classify
# as KIND_TEXT and most are ENUMERATED terms that must keep comparing -
# `construction_type`, `occupancy_type`, `valuation_method`, `sprinkler_system`,
# `entity_type`. A "looks like a phrase" heuristic would silence real conflicts
# on all of them. Adding a key here is a decision about that key.
# `test_no_enumerated_type_field_is_treated_as_narrative` fails the build if one
# of those is ever added.
#
# KNOWN RESIDUAL, stated rather than hidden: two documents naming genuinely
# DIFFERENT trades ("roofing contractor" vs "restaurant") also stop being a
# conflict here. That is judged the lesser risk - a different insured is caught
# by `applicant_name`, and today's behaviour asks the producer a question they
# cannot meaningfully answer.
_SOFT_TEXT_FACT_KEYS = frozenset({
    "contractor_type",
})
_STATE_TOKENS = frozenset({"state", "states"})

# A value of this many words or more is prose. Nobody picks between two true
# paragraphs, so they are INCOMPARABLE rather than same-or-different. 25 is
# deliberately generous: a real free-text FIELD value ("Commercial roofing
# contractor performing re-roofing and repair on commercial structures" - 11
# words) stays comparable, while the client's remarks blocks (40+ words) do not.
_PROSE_WORD_FLOOR = 25


def _tokens(key: str) -> frozenset:
    return frozenset(t for t in re.split(r"[^a-z0-9]+", (key or "").lower()) if t)


_KIND_CACHE: Dict[str, str] = {}


def value_kind(fact_key: str) -> str:
    """The kind of value this fact holds, derived from declarations that already
    exist. Cached - this is called inside grouping loops.

    Resolution order (authoritative first, guessy last):
      1. ``normalization``'s explicit identity sets (name / date / address /
         carrier / FEIN / entity-type) - the same tables ``normalize_value``
         dispatches on, so "how it is compared" and "how it is normalised" can
         never disagree.
      2. ``FACT_REGISTRY``'s declared validator, by function name.
      3. Key-shape tokens, for the 87 facts whose validator is a lambda or None.
      4. ``KIND_TEXT``.
    """
    if fact_key in _KIND_CACHE:
        return _KIND_CACHE[fact_key]
    kind = _resolve_kind(fact_key)
    _KIND_CACHE[fact_key] = kind
    return kind


def _resolve_kind(fact_key: str) -> str:
    key = (fact_key or "").strip()
    if not key:
        return KIND_TEXT

    # 1. Workstream-2's own identity tables (authoritative).
    try:
        from services.normalization import (
            NAME_FIELDS, DATE_FIELDS, ADDRESS_FIELDS, CARRIER_FIELDS,
            FEIN_FIELDS, ENTITY_TYPE_FIELDS, _infer_field_category,
        )
        if key in FEIN_FIELDS:
            return KIND_FEIN
        if key in DATE_FIELDS:
            return KIND_DATE
        if key in ADDRESS_FIELDS:
            return KIND_ADDRESS
        if key in NAME_FIELDS or key in CARRIER_FIELDS:
            return KIND_NAME
        if key in ENTITY_TYPE_FIELDS:
            return KIND_TEXT          # closed-ish set; normalize_value owns it
        from services.normalization import VALUATION_METHOD_FIELDS
        if key in VALUATION_METHOD_FIELDS:
            return KIND_TEXT          # RCV == Replacement Cost, via WS-2
        _cat = _infer_field_category(key)
        if _cat == "date":
            return KIND_DATE
        if _cat == "address":
            return KIND_ADDRESS
        if _cat in ("name", "carrier"):
            return KIND_NAME
    except Exception:                                        # pragma: no cover
        pass

    # 2. The registry's declared validator.
    try:
        from services.fact_registry import FACT_REGISTRY
        entry = FACT_REGISTRY.get(key) or {}
        vname = getattr(entry.get("validate"), "__name__", "")
        if vname in _VALIDATOR_KIND:
            return _VALIDATOR_KIND[vname]
    except Exception:                                        # pragma: no cover
        pass

    # 3. Key shape. Narrative first - a "..._description" holding an amount is
    #    still prose, and reading it as money would compare two paragraphs by
    #    whatever number they happen to contain.
    #
    # `_SOFT_TEXT_FACT_KEYS` (contractor_type) is deliberately NOT dispatched
    # to KIND_NARRATIVE here - it stays KIND_TEXT so containment and truncation
    # still run, and only the final DIFFERENT-vs-INCOMPARABLE choice at the
    # bottom of `same_fact` is softened. See that constant's docstring.
    tk = _tokens(key)
    if tk & _NARRATIVE_TOKENS:
        return KIND_NARRATIVE
    if tk & _PHONE_TOKENS:
        return KIND_PHONE
    if tk & _IDENTIFIER_TOKENS_STRONG:
        return KIND_IDENTIFIER
    if tk & _STATE_TOKENS:
        return KIND_STATE
    if tk & _CODE_TOKENS:
        return KIND_CODE
    if tk & _MONEY_TOKENS:
        return KIND_MONEY
    if tk & _COUNT_TOKENS:
        return KIND_COUNT
    if "indicator" in tk or "required" in tk:
        return KIND_YESNO
    if tk & _IDENTIFIER_TOKENS_WEAK:
        return KIND_IDENTIFIER
    return KIND_TEXT


# ── Shape helpers ────────────────────────────────────────────────────────────

# One money amount: optional $, digits with optional thousands separators, an
# optional decimal, and an optional K/M/MM/B multiplier ("$3M" is how a broker
# writes three million). The multiplier is only ever honoured on a money-typed
# field, so a policy number containing "3M" can never be read as an amount.
_MONEY_RE = re.compile(
    r"(?<![\w.])\$?\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\s?(MM|[KMB])?"
    # A trailing SENTENCE period must not block the match ("$2,000,000." is an
    # amount), but a following digit must ("1.000.000" is not 1). Hence two
    # lookaheads instead of the single (?![\w.]) the first cut used.
    r"(?![\w])(?!\.\d)", re.I)
# "303-996-7800 x212" / "ext. 212" - an extension is not part of the number.
_PHONE_EXT_RE = re.compile(r"\b(?:x|ext\.?|extension)\s*\d+\s*$", re.I)
_MULT = {"K": 1_000, "M": 1_000_000, "MM": 1_000_000, "B": 1_000_000_000}

_YES = frozenset({"y", "yes", "true", "t", "1", "checked", "x"})
_NO = frozenset({"n", "no", "false", "f", "0", "unchecked"})

_US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "puerto rico": "PR",
}


def money_amounts(value: Any) -> List[str]:
    """Every distinct money amount in ``value``, canonicalised.

    Returning a LIST is the safety mechanism, not an implementation detail. The
    money rule only fires when a value carries EXACTLY ONE amount, so a
    composite ("$1,000,000 / $2,000,000", "02 $ 5,000 EACH INSURED . 35.00")
    falls through to text comparison instead of being flattened into a
    meaningless concatenation. Real Orbin dec pages print exactly that shape.
    """
    out: List[str] = []
    for m in _MONEY_RE.finditer(str(value or "")):
        whole, frac, mult = m.group(1), m.group(2), (m.group(3) or "").upper()
        try:
            amt = float(whole.replace(",", "") + ("." + frac if frac else ""))
        except ValueError:                                   # pragma: no cover
            continue
        if mult:
            amt *= _MULT.get(mult, 1)
        canon = str(int(amt)) if amt == int(amt) else f"{amt:.2f}".rstrip("0").rstrip(".")
        if canon not in out:
            out.append(canon)
    return out


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _alnum(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _word_tokens(value: Any) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", str(value or "").lower()) if t]


def is_prose(value: Any) -> bool:
    """True when the value is a paragraph rather than a field value."""
    return len(_word_tokens(value)) >= _PROSE_WORD_FLOOR


def _yesno(value: Any) -> Optional[str]:
    s = str(value or "").strip().lower().rstrip(".")
    if s in _YES:
        return "Y"
    if s in _NO:
        return "N"
    return None


def _state_code(value: Any) -> Optional[str]:
    s = re.sub(r"[^a-z ]", " ", str(value or "").lower())
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) == 2:
        return s.upper()
    return _US_STATES.get(s)


def _url_key(value: Any) -> str:
    s = str(value or "").strip().lower()
    s = re.sub(r"^[a-z]+://", "", s)
    s = re.sub(r"^www\.", "", s)
    return s.rstrip("/")


def _leading_code(value: Any) -> Optional[str]:
    """The code a value starts with, when the remainder is a description.

    ``91580 Contractors - Executive Supervisors`` -> ``91580``. A WORD BOUNDARY
    after the code is mandatory: without it ``91580`` would match ``915801``,
    which is a different class code and a different rate.
    """
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9./-]*)(?=\s|$)", str(value or ""))
    return m.group(1).strip(".,;:").upper() if m else None


def _code_set(value: Any) -> frozenset:
    """The set of codes in a code LIST, leading zeros stripped.

    ``"1, 7"`` and ``"01/07"`` designate the same two covered-auto symbols; the
    separator and the zero-padding are printing conventions, not value. Returns
    an empty set for anything containing a non-code token, so a code plus its
    description never reaches this rule (``_leading_code`` owns that shape).
    """
    toks = [t for t in re.split(r"[^A-Za-z0-9]+", str(value or "")) if t]
    if not toks or any(not t.isalnum() for t in toks):
        return frozenset()
    return frozenset(t.lstrip("0").upper() or "0" for t in toks)


def _is_bare_number(value: Any) -> bool:
    """True when the whole value is one number, optionally with a currency
    symbol, a percent sign or a trailing unit word ("50 miles", "47 full-time").

    The unit allowance is what makes ``50`` and ``50 miles`` the same radius. It
    is bounded to TWO trailing words so a sentence containing a number can never
    qualify - that is the shape that let prose become a candidate value in the
    2026-08-08 incident.
    """
    s = str(value or "").strip()
    return bool(re.fullmatch(
        r"[$]?\s?\d[\d,]*(?:\.\d+)?\s?%?(?:\s+[A-Za-z][A-Za-z./-]*){0,2}", s))


def _contains_whole(short: Sequence[str], long: Sequence[str]) -> bool:
    """True when ``short`` appears as a CONTIGUOUS whole-token run inside
    ``long``. Contiguity is the guard: "Denver CO" genuinely appears inside
    "4800 Dahlia St Denver CO 80216", while a scattered token overlap
    ("Denver" + "80216" against a different street) does not.
    """
    if not short or len(short) >= len(long):
        return False
    n = len(short)
    return any(list(long[i:i + n]) == list(short) for i in range(len(long) - n + 1))


# ── The value test ───────────────────────────────────────────────────────────

def same_fact(fact_key: str, a: Any, b: Any) -> str:
    """SAME / DIFFERENT / INCOMPARABLE for two printings of one fact.

    Pure: no I/O, no context, no session state. Context-dependent suppression
    (two values belonging to two different policies) is a separate decision and
    lives in :class:`PackageContext` - keeping them apart is what lets the value
    test be exhaustively swept in a unit test.
    """
    sa, sb = str(a or "").strip(), str(b or "").strip()
    if not sa or not sb:
        return INCOMPARABLE
    if sa == sb or sa.lower() == sb.lower():
        return SAME

    kind = value_kind(fact_key)

    # A paragraph is never a rival answer - not for a narrative field and not
    # for any other field that happens to have swallowed one.
    #
    # EXCEPT A LIMITS SCHEDULE, WHICH IS LONG BUT IS NOT PROSE. Live Run A,
    # 2026-08-23: `gl_limits` came back a CONFLICT across three printings of one
    # set of limits, because the fullest one -
    #   "$1,000,000 Each Occurrence / $2,000,000 General Aggregate /
    #    $2,000,000 Products-Completed Operations Aggregate / $1,000,000
    #    Personal and Advertising Injury / $100,000 Damage to Premises Rented
    #    to You / $5,000 Medical Expense"
    # - is 36 words, over the 25-word prose floor. The money branch below
    # already owns exactly this case ("a COMPOSITE that lists FEWER limits is
    # not disagreeing - it is saying less"), but the prose gate returned
    # INCOMPARABLE before it could run. That is the client's own "levels of
    # detail" complaint, on a legal limit.
    #
    # The distinguishing signal is POSITIVE and structural: a limits schedule is
    # dense with money amounts, a paragraph is not. Both sides must parse to two
    # or more amounts, and the field must already be money-kind - so a narrative
    # field is untouched (KIND_NARRATIVE is still tested first) and a paragraph
    # that happens to quote a couple of figures on a money field still has to
    # survive the subset test below on its actual amounts.
    _money_composite = (
        kind == KIND_MONEY
        and len(money_amounts(sa)) > 1
        and len(money_amounts(sb)) > 1
    )
    if kind == KIND_NARRATIVE or (
            not _money_composite and (is_prose(sa) or is_prose(sb))):
        return INCOMPARABLE

    # A DATE is a date whatever the key is called. `policy_period` classifies as
    # an identifier by its tokens, and its values are dates - found by the
    # sweep. Checked before the kind dispatch so no kind can mis-own a date.
    if kind not in (KIND_NAME, KIND_ADDRESS, KIND_MONEY):
        try:
            from services.normalization import normalize_date
            _ia, _ib = normalize_date(sa), normalize_date(sb)
            if _ia and _ib:
                return SAME if _ia == _ib else DIFFERENT
        except Exception:                                    # pragma: no cover
            pass

    if kind == KIND_MONEY:
        ma, mb = money_amounts(sa), money_amounts(sb)
        # A COMPOSITE that lists FEWER limits is not disagreeing - it is saying
        # less. Probe run B: the dec page printed "$1,000,000 / $2,000,000 /
        # $2,000,000" and the certificate printed the same three plus
        # "$100,000 damage to rented premises". A certificate routinely prints a
        # subset of the dec page's limits. Same rule as lines of business: only
        # sets that EACH carry something the other lacks genuinely disagree.
        # BOTH sides must be composites. A SINGLE amount against a composite
        # ("$1,000,000" vs "$1,000,000 / $2,000,000") is not a shorter list -
        # it is one value against a structure that also names a larger one, and
        # merging them would undo test_a_composite_amount_is_never_flattened.
        if len(ma) > 1 and len(mb) > 1:
            sa_set, sb_set = set(ma), set(mb)
            if sa_set <= sb_set or sb_set <= sa_set:
                return SAME
        if ma and mb:
            # Same amounts (one each, or an identically-composed block) -> one
            # value. Different amounts -> a real difference, and we stop HERE.
            #
            # Falling through to the text rules was a bug the gate test caught:
            # "$1,000,000" is a contiguous token run inside
            # "$1,000,000 / $2,000,000", so the containment rule merged a
            # single limit with a composite that also contains a second, larger
            # one. A money field never gets a text opinion once both sides have
            # been read as money.
            return SAME if ma == mb else DIFFERENT

    elif kind in (KIND_COUNT, KIND_PERCENT):
        na, nb = money_amounts(sa), money_amounts(sb)
        if len(na) == 1 and len(nb) == 1:
            return SAME if na[0] == nb[0] else DIFFERENT

    elif kind == KIND_PHONE:
        da = _digits(_PHONE_EXT_RE.sub("", sa))
        db = _digits(_PHONE_EXT_RE.sub("", sb))
        if len(da) >= 10 and len(db) >= 10:
            # Last 10 digits: a leading country/trunk prefix must not split one
            # number into two. The extension is stripped above rather than
            # absorbed here, so two genuinely different numbers cannot align.
            return SAME if da[-10:] == db[-10:] else DIFFERENT

    elif kind == KIND_EMAIL:
        return SAME if sa.lower() == sb.lower() else DIFFERENT

    elif kind == KIND_URL:
        return SAME if _url_key(sa) == _url_key(sb) else DIFFERENT

    elif kind == KIND_FEIN:
        da, db = _digits(sa), _digits(sb)
        if len(da) == 9 and len(db) == 9:
            return SAME if da == db else DIFFERENT

    elif kind == KIND_DATE:
        try:
            from services.normalization import normalize_date
            ia, ib = normalize_date(sa), normalize_date(sb)
            if ia and ib:
                return SAME if ia == ib else DIFFERENT
        except Exception:                                    # pragma: no cover
            pass

    elif kind == KIND_YESNO:
        ya, yb = _yesno(sa), _yesno(sb)
        if ya and yb:
            return SAME if ya == yb else DIFFERENT

    elif kind == KIND_STATE:
        ca, cb = _state_code(sa), _state_code(sb)
        if ca and cb:
            return SAME if ca == cb else DIFFERENT

    elif kind == KIND_CODE:
        ca, cb = _leading_code(sa), _leading_code(sb)
        if ca and cb and ca == cb:
            return SAME                       # code + its printed description
        # A code LIST is a set, not a string: "1, 7" and "01/07" designate the
        # same two covered-auto symbols. Leading zeros are printing, not value.
        la, lb = _code_set(sa), _code_set(sb)
        if la and lb and la == lb:
            return SAME
        return DIFFERENT if (ca and cb) else INCOMPARABLE

    elif kind == KIND_IDENTIFIER:
        # OCR letter-spacing ("6 C 7 - 4 0 - 0 2---26") and punctuation-only
        # differences ("BBC7263 - 26") are printings of one contract. A value
        # that is a strict alphanumeric PREFIX of the other is NOT merged here -
        # "6E74002" vs "6E7-40-02---26" really are two printings, but proving it
        # needs the canonical joiner, which lives in extraction_service and is
        # applied upstream of this module.
        if _alnum(sa) and _alnum(sa) == _alnum(sb):
            return SAME
        return DIFFERENT

    # ── Entity names: the CONFLICT-grade comparator, never the coarse one ────
    # `normalize_name` / `normalize_carrier` deliberately collapse an LLC with
    # an Inc and EMC P&C with Employers Mutual - correct for document
    # clustering, catastrophic here (Round 10 fix 46 exists for exactly that).
    # `strict_entity_key` is the comparator built for this question: it folds
    # spelling ("&"/"and", Co/Company, L.L.C./LLC) and nothing else.
    if kind == KIND_NAME:
        try:
            from services.normalization import strict_entity_key
            ka, kb = strict_entity_key(sa), strict_entity_key(sb)
            if ka and kb and ka == kb:
                return SAME
        except Exception:                                    # pragma: no cover
            pass

    # ── Addresses: compare through WS-2's address normaliser, then containment.
    # It resolves Street/ST and Colorado/CO, which is what makes the client's
    # "full street address vs Denver, Colorado" a component rather than a rival.
    if kind == KIND_ADDRESS:
        try:
            from services.normalization import normalize_address
            na, nb = normalize_address(sa), normalize_address(sb)
            if na and nb:
                if na == nb:
                    return SAME
                wa, wb = na.split(), nb.split()
                if _contains_whole(wa, wb) or _contains_whole(wb, wa):
                    return SAME
                return DIFFERENT
        except Exception:                                    # pragma: no cover
            pass

    # ── Value-shape fallback ────────────────────────────────────────────────
    # The kind tables cover the fields we can name; this covers the ones we
    # cannot. If BOTH printings are a single number, or both parse as dates,
    # they are comparable as such whatever the key is called. Deliberately NOT
    # applied to names/addresses (handled above) or narrative (already exited).
    if kind not in (KIND_NAME, KIND_ADDRESS):
        na_, nb_ = money_amounts(sa), money_amounts(sb)
        if len(na_) == 1 and len(nb_) == 1 and _is_bare_number(sa) and _is_bare_number(sb):
            return SAME if na_[0] == nb_[0] else DIFFERENT
        try:
            from services.normalization import normalize_date
            ia, ib = normalize_date(sa), normalize_date(sb)
            if ia and ib:
                return SAME if ia == ib else DIFFERENT
        except Exception:                                    # pragma: no cover
            pass

    # ── Text ────────────────────────────────────────────────────────────────
    ta, tb = _word_tokens(sa), _word_tokens(sb)
    if ta and tb:
        if ta == tb:
            return SAME
        # A component is not a competitor: "Denver, Colorado" sits inside the
        # full street address. Only ever prefers the FULLER value; the caller
        # additionally requires the fragment to fit exactly ONE other group.
        if _contains_whole(ta, tb) or _contains_whole(tb, ta):
            return SAME
        # One printing cut off mid-word ("Commercia" / "Commercial roofing
        # contractor") is the SAME value truncated, not a rival. Reuses the
        # extraction layer's own test, which requires the break to be mid-word
        # - a continuation at a word boundary is a QUALIFIED value and is left
        # alone (that distinction is documented at its definition).
        try:
            from services.extraction_service import _is_midword_truncation
            if _is_midword_truncation(sa, sb) or _is_midword_truncation(sb, sa):
                return SAME
        except Exception:                                    # pragma: no cover
            pass

    # Last resort: Workstream-2's own equivalence for this field (insurance
    # synonyms - CGL, CSL, RCV/Replacement Cost). Safe here because names,
    # carriers and addresses have already been decided above by the comparators
    # built for them; this only reaches plain text and unclassified keys.
    if kind not in (KIND_NAME, KIND_ADDRESS):
        try:
            from services.normalization import normalize_value
            va, vb = normalize_value(fact_key, sa), normalize_value(fact_key, sb)
            if va and vb and va == vb:
                return SAME
        except Exception:                                    # pragma: no cover
            pass

    # A SOFT TEXT field (client 1.1 "levels of detail") gets one more chance
    # before DIFFERENT: two phrasings neither containment nor truncation nor
    # the synonym table could reconcile are not proven to disagree, only
    # unreconciled. See `_SOFT_TEXT_FACT_KEYS` for the reasoning and the
    # known residual it accepts.
    if fact_key in _SOFT_TEXT_FACT_KEYS:
        return INCOMPARABLE
    return DIFFERENT


# ── Package context (which contract does a value belong to?) ─────────────────

_FACT_LINE_CACHE: Dict[str, Optional[str]] = {}


def fact_line(fact_key: str) -> Optional[str]:
    """The canonical coverage line this fact belongs to, or None.

    Derived by intersecting the fact's own ``FACT_REGISTRY["forms"]`` with
    ``pdf_service._SECTION_FORM_LINE_PHRASES`` - the table that already encodes
    which ACORD forms are LINE sections and which are package-level. ACORD 125
    and 101 are deliberately absent from that table (their scalars are
    package-level), so ``policy_number`` and ``effective_date`` correctly get no
    line and are never touched by the foreign-value rule below.

    Returns None whenever the answer is not unambiguous - a fact reaching two
    forms of different lines has no single line, and guessing one would blank a
    legitimate value.
    """
    if fact_key in _FACT_LINE_CACHE:
        return _FACT_LINE_CACHE[fact_key]
    line = None
    try:
        from services.fact_registry import FACT_REGISTRY
        from services.pdf_service import _SECTION_FORM_LINE_PHRASES
        from services.lob_canon import canon_line as _canon_line
        forms = (FACT_REGISTRY.get(fact_key) or {}).get("forms") or set()
        # EVERY form must be a line SECTION, and they must agree on one line.
        # A fact that also reaches ACORD 125/101 is package-level by definition
        # - those two are deliberately absent from the section table. Requiring
        # only SOME form to be a section gave `carrier_name` (forms 125 + 126)
        # the General Liability line, and the foreign-value rule then deleted
        # "EMC Property & Casualty Company" because the CARRIER'S OWN NAME
        # contains the word "Property". Caught by
        # test_the_two_real_carriers_finally_conflict, which is Round 10's
        # regression guard doing exactly its job.
        if forms and all(f in _SECTION_FORM_LINE_PHRASES for f in forms):
            lines = set()
            for fid in forms:
                for phrase in _SECTION_FORM_LINE_PHRASES.get(fid, ()):
                    c = _canon_line(phrase)
                    if c:
                        lines.add(c)
            if len(lines) == 1:
                line = next(iter(lines))
    except Exception:                                        # pragma: no cover
        line = None
    _FACT_LINE_CACHE[fact_key] = line
    return line


def names_a_foreign_line(fact_key: str, value: Any) -> bool:
    """True when ``value`` names a DIFFERENT coverage line than ``fact_key``.

    Client 2026-08-17 item 2: *"GL Form Type: BUSINESS AUTO COVERAGE FORM vs
    Commercial General Liability - those are different lines of business, not
    competing GL values."* A Business Auto form name is not a candidate answer
    for a General Liability field, so the producer must never be asked to choose
    between them.

    POSITIVE EVIDENCE ONLY, in both directions: the fact must have an
    unambiguous line AND the value must canonicalise to a line, and they must
    differ. ``"Occurrence"`` names no line and is untouched;
    ``"Commercial General Liability"`` names the fact's OWN line and is
    untouched. Only a value belonging to somebody else is rejected.
    """
    # SECOND GUARD, deliberately independent of the first. An ENTITY NAME or an
    # ADDRESS may not be read as a line name at any time: real carriers are
    # called "EMC Property & Casualty Company", "Employers Mutual Casualty",
    # "Great American Umbrella" - the coverage word is part of the company's
    # name, not a statement about coverage. One guard would have been enough
    # here; two, because deleting a real carrier is unrecoverable for the user
    # and the failure is silent.
    if value_kind(fact_key) in (KIND_NAME, KIND_ADDRESS, KIND_NARRATIVE):
        return False
    own = fact_line(fact_key)
    if not own:
        return False
    from services.lob_canon import canon_line as _canon_line
    theirs = _canon_line(value)
    return bool(theirs) and theirs != own


class PackageContext:
    """What the VERIFIED dec index knows about this package's contracts.

    Client 2026-08-17: *"multiple policy numbers or carriers on a multi-line
    account should only be treated as conflicting if Primble establishes that
    they belong to the same policy and coverage context."* Establishing it needs
    evidence, and the evidence already exists - ``dec_page_entries`` carries
    label + value + policy_number + line_of_business for every printed value and
    is verified verbatim against the document text before it is stored. Nothing
    in the conflict layer had ever read it.

    POSITIVE EVIDENCE ONLY. Every method answers "cannot tell" rather than
    guessing, and a caller that cannot tell keeps today's behaviour. A package
    with no dec index behaves exactly as it does now.
    """

    __slots__ = ("contracts", "value_owner", "line_level_values",
                 "package_level_values", "contract_line",
                 "item_owner", "item_columns", "_ok")

    def __init__(self, merged_facts: Optional[dict] = None,
                 docs: Optional[List[dict]] = None):
        self.contracts: set = set()
        self.value_owner: Dict[str, set] = {}
        self.line_level_values: set = set()
        self.package_level_values: set = set()
        # contract (alnum policy number) -> canonical coverage line(s) it is
        # printed under. V1 plan C1 F2b: two policies on the SAME line in one
        # period are not two scopes, they are a question for the producer.
        self.contract_line: Dict[str, set] = {}
        # ── THE ITEM AXIS (client 1.2: "location; vehicle/property/item") ────
        # value token -> the schedule row(s) that print it, e.g.
        # {"2014": {"property_locations#0"}}. Two values printed by DIFFERENT
        # rows describe different physical things and are not rival answers.
        self.item_owner: Dict[str, set] = {}
        # Fact keys PROVEN to vary per item, because the package's own rows
        # carry a column of that exact name. This gate is the whole safety
        # story - see `_build_item_index`.
        self.item_columns: set = set()
        self._ok = False
        try:
            self._build(merged_facts or {}, docs or [])
            self._ok = True
        except Exception as exc:                             # noqa: BLE001
            logger.warning("fact_equivalence: context build failed - %s", exc)

    # -- construction --------------------------------------------------------
    def _build(self, merged_facts: dict, docs: List[dict]) -> None:
        entries: List[dict] = []
        for src in [merged_facts] + [(d.get("facts") or {}) for d in docs]:
            got = src.get("dec_page_entries") if isinstance(src, dict) else None
            if isinstance(got, list):
                entries.extend(e for e in got if isinstance(e, dict))

        from services.lob_canon import canon_line as _canon_line
        try:
            from services.extraction_service import _looks_like_a_policy_number
        except Exception:                                    # pragma: no cover
            _looks_like_a_policy_number = lambda _s: False   # noqa: E731

        for e in entries:
            pol = str(e.get("policy_number") or "").strip()
            line = _canon_line(e.get("line_of_business")) or _canon_line(e.get("section"))
            if pol and _looks_like_a_policy_number(pol):
                self.contracts.add(_alnum(pol))
                if line:
                    self.contract_line.setdefault(_alnum(pol), set()).add(line)
            # The owner of a printed VALUE: prefer the contract, fall back to
            # the coverage line. Either is enough to say "these two values
            # describe different things".
            owner = _alnum(pol) if pol and _looks_like_a_policy_number(pol) else (line or "")
            val = _alnum(e.get("value"))
            if val and owner:
                self.value_owner.setdefault(val, set()).add(owner)
            if val and line:
                self.line_level_values.add(val)
            elif val and not pol:
                # Printed under NO line and NO policy - a package-level figure.
                # Recorded so the component rule can require evidence on BOTH
                # sides (see is_component_of_package).
                self.package_level_values.add(val)

        # `coverage_lines` is a second witness, and often a CLEANER one. Probe
        # run 1 (2026-08-17): the dec entries' carrier values came back OCR-
        # garbled ("EMC Property & Casualty Compa0y7") so no carrier could be
        # attributed and a two-carrier multi-line account still raised a
        # conflict - while `coverage_lines` held both names intact. It is also
        # repaired upstream by `_repair_coverage_lines_from_entries`, so a
        # corrupt line->policy pairing has already been rebuilt from the
        # verified entries before this reads it.
        for ln in (merged_facts.get("coverage_lines") or []):
            if not isinstance(ln, dict):
                continue
            pn_raw = str(ln.get("policy_number") or "")
            pn = _alnum(pn_raw)
            line = _canon_line(ln.get("line"))
            if pn and _looks_like_a_policy_number(pn_raw):
                self.contracts.add(pn)
                if line:
                    self.contract_line.setdefault(pn, set()).add(line)
            owner = pn or line
            if not owner:
                continue
            for val in (ln.get("carrier"), pn_raw):
                v = _alnum(val)
                if v:
                    self.value_owner.setdefault(v, set()).add(owner)
                    if line:
                        self.line_level_values.add(v)

        self._build_item_index(merged_facts)

    # ── The item index (client 1.2) ─────────────────────────────────────────
    # A schedule row IS a scope: `property_locations[1]` is a different building
    # from `property_locations[0]`, so two different `year_built` values printed
    # by those two rows are two facts, not a contradiction. Before this, a
    # two-building package raised a Data Consistency question for every column
    # where the buildings legitimately differ.
    #
    # TWO GATES, and both are needed. B14 is the reason: `value_owner` keys on
    # a value's own CHARACTERS, so the certificate's umbrella $1,000,000
    # inherited the GL policy's ownership purely because the dec page prints
    # $1,000,000 as the GL Each Occurrence limit, and the client's real
    # $3M-vs-$1M conflict was scoped into silence.
    #
    #   Gate 1 - THE FACT MUST BE PROVEN PER-ITEM. Only a fact key that is
    #     literally a column name in one of this package's own schedules may be
    #     item-scoped. Exact match, never a suffix: `total_payroll` ends with
    #     `payroll`, which is a wc_class_codes column, and the package TOTAL is
    #     emphatically not a per-class figure.
    #   Gate 2 - THE OWNERSHIP MUST BE DISJOINT AND NON-EMPTY on both sides. A
    #     coincidental character match can only ADD owners, which makes an
    #     overlap MORE likely and scoping LESS likely, so the failure mode is
    #     "show the conflict" - the safe direction.
    #
    # CONTRACT INDEXES ARE EXCLUDED, and derived rather than named: a list whose
    # rows carry `policy_number` / `line` / `line_of_business` is a contract
    # index (`coverage_lines`, `dec_page_entries`), and those belong to the
    # POLICY axis above, which has its own proven overlap rules. Letting them
    # in would give `policy_number` a second, weaker route to being scoped that
    # bypasses the "two policies on the same coverage line" check.
    _CONTRACT_ROW_KEYS = ("policy_number", "line", "line_of_business")

    def _build_item_index(self, merged_facts: dict) -> None:
        if not isinstance(merged_facts, dict):
            return
        for list_key, rows in merged_facts.items():
            if not list_key or str(list_key).startswith("_"):
                continue
            if not isinstance(rows, list) or len(rows) < 2:
                continue                  # one row cannot separate two values
            dict_rows = [r for r in rows if isinstance(r, dict)]
            if len(dict_rows) < 2:
                continue
            if any(k in r for r in dict_rows for k in self._CONTRACT_ROW_KEYS):
                continue                  # a contract index, not an item schedule
            for idx, row in enumerate(dict_rows):
                item_id = f"{list_key}#{idx}"
                for col, val in row.items():
                    if not col or str(col).startswith("_"):
                        continue
                    if isinstance(val, (list, dict)) or val is None:
                        continue
                    token = _alnum(val)
                    if not token:
                        continue
                    self.item_columns.add(str(col))
                    self.item_owner.setdefault(token, set()).add(item_id)

    def items_of(self, value: Any) -> set:
        """Schedule row(s) that print this value."""
        return self.item_owner.get(_alnum(value), set()) if self._ok else set()

    def is_item_scoped_fact(self, fact_key: Any) -> bool:
        """Gate 1: does this package's own data prove the fact varies per item?"""
        return bool(self._ok and fact_key and str(fact_key) in self.item_columns)

    def different_items(self, a: Any, b: Any) -> bool:
        """PROOF that two values were printed by different schedule rows."""
        ia, ib = self.items_of(a), self.items_of(b)
        return bool(ia and ib and not (ia & ib))

    # -- queries -------------------------------------------------------------
    @property
    def is_multi_contract(self) -> bool:
        """Two or more distinct contracts are evidenced in this package."""
        return self._ok and len(self.contracts) >= 2

    def lines_of_owner(self, owner: Any) -> set:
        """Canonical coverage line(s) an owner token stands for. A contract
        maps through ``contract_line``; a bare line token maps to itself."""
        if not self._ok:
            return set()
        o = str(owner or "")
        if o in self.contract_line:
            return set(self.contract_line[o])
        return {o} if o else set()

    def owners_of(self, value: Any) -> set:
        return self.value_owner.get(_alnum(value), set()) if self._ok else set()

    def different_owners(self, a: Any, b: Any) -> bool:
        """PROOF that two values describe different contracts / coverage lines.

        Both must be positively attributed, and their owner sets must be
        disjoint. An unattributed value, a shared owner, or no index at all all
        return False - the conflict then stands, which is the safe direction.
        """
        oa, ob = self.owners_of(a), self.owners_of(b)
        if not (oa and ob) or (oa & ob):
            return False
        # Two contracts on the SAME coverage line in one package are not
        # proof of two scopes - a GL policy number twice is a question for the
        # producer, not a formatting difference (V1 plan C1 F2b). Only when
        # the owners resolve to disjoint lines (or carry no line at all) is
        # the difference explained.
        la = set().union(*(self.lines_of_owner(o) for o in oa)) if oa else set()
        lb = set().union(*(self.lines_of_owner(o) for o in ob)) if ob else set()
        la = {x for x in la if x not in self.contract_line}    # line tokens only
        lb = {x for x in lb if x not in self.contract_line}
        return not (la & lb)

    def same_contract_printing(self, a: Any, b: Any) -> bool:
        """True when two printings name ONE contract in this package.

        ``6E7-40-02---26`` and ``6E74002`` are the same auto policy printed two
        ways one page apart (client audit 2026-08-16). The election rule is
        ``pdf_service._canonical_policy_printing``'s, verbatim: prefix-match in
        either direction, and EXACTLY ONE canonical key may claim a printing -
        an ambiguous stub that matches several policies stays unresolved.
        Context-dependent by nature, which is why it lives here and not in the
        pure value test.
        """
        if not self._ok or not self.contracts:
            return False
        na, nb = _alnum(a).upper(), _alnum(b).upper()
        if len(na) < 4 or len(nb) < 4:
            return False
        ka = {c for c in self.contracts
              if c.upper().startswith(na) or na.startswith(c.upper())}
        kb = {c for c in self.contracts
              if c.upper().startswith(nb) or nb.startswith(c.upper())}
        return len(ka) == 1 and ka == kb

    def is_component_of(self, part: Any, whole: Any) -> bool:
        """True when ``part`` is a LINE figure and ``whole`` is the PACKAGE
        figure - one is a piece of the other, not a rival to it.

        Probe run C: ``$10,663`` is the package total premium and ``$2,991`` the
        Commercial Auto line premium, printed on the same dec page.

        EVIDENCE IS REQUIRED ON BOTH SIDES, and that is not fussiness. The first
        cut asked only "is this value line-attributed?", which made the
        umbrella's own $3,000,000 a "component" - so it merged with the COI's
        $1,000,000 and silently destroyed the one conflict the client praised.
        The gate test caught it. A value that is merely UNKNOWN to the index is
        not a package figure, and cannot pair with anything.
        """
        if not self._ok:
            return False
        p, w = _alnum(part), _alnum(whole)
        if not p or not w or p == w:
            return False
        return p in self.line_level_values and w in self.package_level_values


# ── The filter (the only thing callers need) ─────────────────────────────────

def _owner_split_allowed(fact_key: str) -> bool:
    """May "these belong to different contracts" excuse a difference here?

    NO for two families, both learned the hard way (v1-20AUG C1-H):

    * **A fact pinned to ONE coverage line.** ``umbrella_limit`` IS the
      umbrella's limit; it cannot have one value per policy, so two values are
      a real disagreement. ``fact_line()`` is exactly the test for "the
      registry can place this fact on a line".
    * **Money.** ``PackageContext`` keys ownership on the value's own
      characters, so any two facts that share an amount share an owner - an
      accidental identity, not a real one. Identifiers, carrier names and dates
      do not collide that way.

    Everything else (policy numbers, carriers, terms) keeps the behaviour.
    """
    try:
        if fact_line(fact_key):
            return False
        return value_kind(fact_key) != KIND_MONEY
    except Exception:                                        # pragma: no cover
        return True


_COMPONENT_KINDS = frozenset({KIND_MONEY, KIND_COUNT, KIND_PERCENT})


def _component_split_allowed(fact_key: str) -> bool:
    """May "one of these is a PIECE of the other" excuse a difference here?

    ONLY FOR QUANTITIES. `is_component_of` exists for exactly one situation,
    and its own docstring is entirely about it: a LINE premium is part of the
    PACKAGE premium, so `$2,991` and `$10,663` are not rivals. That reasoning
    has no meaning for anything that is not a quantity - an address is never a
    component of another address, a carrier is never a component of another
    carrier, a date is never part of another date.

    LIVE REGRESSION 2026-08-23 (Run B) is why this gate exists. `is_component_of`
    compares `_alnum(value)`, which on an address yields a meaningless token
    (`4800DahliaStD13DenverCO802163121`). The package's verified index happened
    to record the Denver address as a line-level value and the LAKEWOOD address
    as a package-level one, so the rule fired and pronounced two materially
    different premises the same fact. The client's original complaint, produced
    by the machinery built to fix it.

    THIS IS THE SECOND TIME A CONTEXT RULE KEYED ON A VALUE'S CHARACTERS HAS
    SILENCED A REAL CONFLICT. The first was C1-H / B14, where the certificate's
    umbrella `$1,000,000` inherited the GL policy's ownership because the dec
    page prints that same amount as the GL limit; `_owner_split_allowed` is the
    gate that was added then. `is_component_of` was left ungated. Both rules
    now have to say which FACTS they may speak about.
    """
    try:
        return value_kind(fact_key) in _COMPONENT_KINDS
    except Exception:                                        # pragma: no cover
        return False


def equivalent_index(fact_key: str, values: Sequence[Any],
                     context: Optional[PackageContext] = None,
                     ) -> Optional[Dict[int, int]]:
    """Map each value's index to the index of the value it is the same as.

    Returns None when nothing merges (the caller keeps its groups untouched) or
    when the field/values cannot be judged.

    THE AMBIGUITY GUARD: a value merges only when it is SAME as exactly ONE
    other. "Denver, Colorado" sitting inside BOTH "4800 Dahlia St, Denver CO"
    and "900 Elm St, Denver CO" is not evidence that the two streets are one
    place - it is evidence that the fragment cannot be placed, so it stays put
    and the genuine two-address conflict survives. Same rule
    ``_consolidate_property_locations`` already applies to location fragments.
    """
    n = len(values)
    if n < 2:
        return None
    try:
        partners: Dict[int, List[int]] = {}
        incomparable: set = set()
        for i in range(n):
            for j in range(i + 1, n):
                verdict = same_fact(fact_key, values[i], values[j])
                if verdict == SAME:
                    partners.setdefault(i, []).append(j)
                    partners.setdefault(j, []).append(i)
                elif verdict == INCOMPARABLE:
                    incomparable.add(i)
                    incomparable.add(j)
                elif context is not None:
                    # Values that genuinely differ as TEXT but that the package's
                    # own verified index explains are not a disagreement either
                    # (client item 2). Three proofs, all positive-evidence:
                    #   * they belong to different contracts / coverage lines
                    #   * one is a LINE figure and the other the package total
                    #   * they are two printings of ONE contract number
                    #
                    # `different_owners` is GATED - see _owner_split_allowed.
                    # It attributes a value by the value's own characters, so
                    # two facts sharing an AMOUNT share an owner. On the first
                    # live run that silenced the client's $3M-vs-$1M umbrella
                    # conflict: the certificate's umbrella $1,000,000 inherited
                    # the GL policy's ownership because the dec page prints
                    # $1,000,000 as the GL Each Occurrence limit.
                    _component_ok = _component_split_allowed(fact_key)
                    if ((_owner_split_allowed(fact_key)
                         and context.different_owners(values[i], values[j]))
                            or context.same_contract_printing(values[i], values[j])
                            or (_component_ok
                                and context.is_component_of(values[i], values[j]))
                            or (_component_ok
                                and context.is_component_of(values[j], values[i]))):
                        partners.setdefault(i, []).append(j)
                        partners.setdefault(j, []).append(i)

        mapping: Dict[int, int] = {}
        # ── Cliques first (V1 plan C1, defect B1 / decision D7) ──────────────
        # The exactly-one rule below is the ambiguity guard: "Denver, Colorado"
        # sitting inside TWO different street addresses must not merge. But
        # it could not tell that case from THREE printings of ONE address,
        # where every value has two partners because all three are the same
        # thing - so the client's literal trio (ZIP+4 / ZIP5 / city-state)
        # stayed three groups and capped the score at 85. The distinguishing
        # signal: in a false-conflict clique every PAIR is partnered; in the
        # two-hosts case the hosts are NOT partnered with each other. So a
        # connected component in which every pair is partnered is one value,
        # and merges whole. A component with any unpartnered pair falls
        # through to the exactly-one rule untouched, which is what keeps
        # test_a_fragment_matching_two_hosts_is_not_merged green.
        adj = {i: set(m) for i, m in partners.items()}
        visited: set = set()
        for start in sorted(adj):
            if start in visited:
                continue
            comp, stack = set(), [start]
            while stack:
                node = stack.pop()
                if node in comp:
                    continue
                comp.add(node)
                stack.extend(adj.get(node, ()) - comp)
            visited |= comp
            if len(comp) < 3:
                continue                       # pairs are the exactly-one rule's job
            is_clique = all(b in adj.get(a, ()) for a in comp for b in comp if a != b)
            if not is_clique:
                continue
            keep = min(comp)
            for i in comp:
                if i != keep and _prefer(fact_key, values[i], values[keep]):
                    keep = i
            for i in comp:
                if i != keep:
                    mapping[i] = keep
        for i, mates in partners.items():
            if i in mapping or i in mapping.values():
                continue                       # already settled by a clique
            if len(set(mates)) != 1:
                continue                       # ambiguous - leave it alone
            j = mates[0]
            if len(set(partners.get(j, []))) != 1:
                continue
            keep = i if _prefer(fact_key, values[i], values[j]) else j
            drop = j if keep == i else i
            mapping[drop] = keep
        if incomparable and len(incomparable) == n:
            # Every value is prose: there is no question to ask at all. The
            # caller collapses them so no row is produced, and keeps OWNING the
            # key so the crude catch-all detector cannot re-report it (measured
            # 2026-08-17: dropping ownership moves the row, it does not remove
            # it).
            first = min(incomparable)
            for i in incomparable:
                if i != first:
                    mapping[i] = first
        return mapping or None
    except Exception as exc:                                 # noqa: BLE001
        logger.warning("fact_equivalence: merge failed for %s - %s", fact_key, exc)
        return None


def _prefer(fact_key: str, a: Any, b: Any) -> bool:
    """True when ``a`` is the better printing to keep as the display value.

    NOT the old "longer string wins" rule, which is what put
    ``$2,000,000 (any one premises)`` and ``BUSINESS AUTO COVERAGE FORM`` in
    front of a producer with a "Suggested" badge on them. For a typed value the
    CLEANEST printing is the right one to show; only for genuinely descriptive
    text is more detail better.
    """
    kind = value_kind(fact_key)
    sa, sb = str(a or "").strip(), str(b or "").strip()
    # BARE wins where the extra characters are an ANNOTATION the form does not
    # want in the box: "$2,000,000", not "$2,000,000 (any one premises)".
    if kind in (KIND_MONEY, KIND_COUNT, KIND_PERCENT, KIND_CODE,
                KIND_YESNO, KIND_STATE, KIND_URL, KIND_EMAIL):
        return len(sa) <= len(sb)
    # FULLER wins where the extra characters are COMPLETENESS: the canonical
    # policy printing over a stub, a four-digit year over two, a ZIP+4 address.
    return len(sa) >= len(sb)
