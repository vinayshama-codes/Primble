"""An AI value must hold the ROLE of its box, not merely be in the documents.

Round 5, 7 Oct 2026 - the owner's live run of the Choice Electric package
(session b248c194, real AI fill). Every value below was found somewhere in the
uploaded text, so the raw-text check called it "verified"; every one sat in a
box whose own meaning is a different thing:

  * ACORD 140 FIRE PROTECTION description = "FRAME" - the CONSTRUCTION type.
  * ACORD 130 HIGHEST FLOOR = "1" twice - the LOC number; no document states a
    floor or a storey.
  * ACORD 130 WC DEDUCTIBLE = "$500" - the WC rating line "0930 Waiver of Our
    Right to Recover ... 0.0200 500.00", a PREMIUM.
  * ACORD 130 producer CELL phone and CSR = the account's contact phone and
    contact name - roles the account profile never states.

One rule per CLASS, measured on the stored corpus (690 sessions), never on the
fixture. Each rule acts on AI-written values only (`gpt_filled_set`): a fact,
a resolver, an alias stamp or a person's value is never judged here. Each
removal returns "CODE: short reason" - the code is what the guard report
records (`_guard_reasons`), the reason is logged with it.

(The fifth class of the round - a BINDER date on a package with no binder - is
an owned blank, not a guard: see `binder_box_owned_blank`, which
`pdf_service._resolve_policy_status` consults, so the model is never asked.)

Fix C (14 Oct 2026) adds (e2): the applicant's general contact copied into an
accounting / claims / inspection contact no document names.
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ── Reason codes (one per class; the guard report records the code) ─────────
R_OTHER_FACT = "VALUE_OF_ANOTHER_FACT"
R_COUNT = "COUNT_WITHOUT_LABELLED_WITNESS"
R_PREMIUM = "PREMIUM_LINE_AMOUNT"
R_PRODUCER_ROLE = "PRODUCER_ROLE_NOT_STATED"


def _fv(facts: Any, key: str) -> Any:
    v = (facts or {}).get(key) if isinstance(facts, dict) else None
    return v.get("value") if isinstance(v, dict) and "value" in v else v


def _key(value: Any) -> str:
    """Formatting-insensitive identity: case, punctuation and spacing are
    formatting ("NON-COMBUSTIBLE" == "Non Combustible")."""
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _words(text: Any) -> List[str]:
    """Lower-case words of a box name ("BuildingFireProtection_Alarm" ->
    building, fire, protection, alarm) or of plain text."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(text or ""))
    return re.findall(r"[a-z]+", s.lower())


def _singular(word: str) -> str:
    try:
        from services.pdf_service import _count_word
        return _count_word(word)
    except Exception:                                       # pragma: no cover
        return word


def _same_word(a: str, b: str) -> bool:
    """One word, two spellings: singular forms equal, or they share their
    first six letters ("construction" / "constructed"), or the shorter (4+
    letters) begins the longer ("roof" / "roofing")."""
    a, b = _singular(a), _singular(b)
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 6:
        return short[:6] == long_[:6]
    return len(short) >= 4 and long_.startswith(short)


def _box_text_words(field: str, schema: dict) -> Tuple[List[str], List[str]]:
    """(the box's name words, its ACORD tooltip words)."""
    base = re.sub(r"_[A-N]\d?$", "", str(field or ""))
    meta = schema.get(field) if isinstance(schema, dict) else None
    tip = str((meta or {}).get("tu") or "") if isinstance(meta, dict) else ""
    return _words(base.replace("_", " ")), _words(tip)


def _tooltip(field: str, schema: dict) -> str:
    meta = schema.get(field) if isinstance(schema, dict) else None
    return str((meta or {}).get("tu") or "") if isinstance(meta, dict) else ""


def _is_checkbox(field: str, schema: dict) -> bool:
    meta = schema.get(field) if isinstance(schema, dict) else None
    return isinstance(meta, dict) and str(meta.get("ft") or "") == "/Btn"


# ══ (a) ANOTHER FACT'S CATEGORICAL VALUE ══════════════════════════════════════
# The facts whose value is a CATEGORY of the risk - a word from a closed
# vocabulary describing the building, the entity, the coverage form - and so
# can be copied whole into any free-text box the model is unsure of. Keys only;
# the words a box must share to TAKE one of these values are read off the key
# itself (minus the generic words below), never a list of ours. A schedule
# row's column of the same name (`property_locations[].construction_type`) is
# the same fact.
_CATEGORICAL_FACTS: Tuple[str, ...] = (
    "construction_type", "builders_risk_construction_type", "occupancy_type",
    "roof_material", "entity_type", "fire_protection_class", "protection_class",
    "sprinkler_system", "sprinkler", "valuation_method",
    "auto_physical_damage_valuation", "cause_of_loss", "fire_department_type",
    "deductible_basis", "auto_vehicle_use", "wc_payroll_period", "gl_form_type",
)
# Words of a fact key that name its SHAPE, not its subject ("construction
# TYPE", "valuation METHOD") - and line abbreviations that name no subject.
_KEY_GENERIC_WORDS = frozenset({
    "type", "code", "class", "method", "system", "plan", "period", "basis",
    "form", "structure", "kind", "the", "of", "and", "auto", "gl", "wc",
    "builders", "risk",
    # "fire" names the ACORD 140's whole fire-protection SECTION - every box in
    # it says fire - so it cannot tell the department's box from the district's
    # (13 Oct 2026, run `ba7c709d` W11: the fire department TYPE "Professional"
    # printed as the fire DISTRICT NAME; the subject is "department").
    "fire",
})
# Values that are not a category at all - a box may hold them for any reason.
_NOT_CATEGORICAL = frozenset({
    "yes", "no", "y", "n", "none", "n a", "na", "nil", "other", "unknown",
    "true", "false", "included", "excluded", "not applicable", "various",
    "tbd", "see schedule", "see attached",
})
_MAX_CATEGORY_WORDS = 6
_MAX_CATEGORY_CHARS = 40


def _concept_words(fact_key: str) -> List[str]:
    return [w for w in _words(fact_key.replace("_", " "))
            if w not in _KEY_GENERIC_WORDS and len(w) >= 3]


def _categorical_value(value: Any) -> Optional[str]:
    """The comparison key of a value that can be a category, else None: a
    short run of words, no digit (a protection class "3", a year, an amount
    are other rules' business), not a Yes/No or a placeholder."""
    s = str(value or "").strip()
    if not s or len(s) > _MAX_CATEGORY_CHARS or re.search(r"\d", s):
        return None
    k = _key(s)
    if not k or k in _NOT_CATEGORICAL or len(re.sub(r"[^a-z]", "", k)) < 3:
        return None
    if len(k.split()) > _MAX_CATEGORY_WORDS:
        return None
    return k


def _categorical_values(facts: dict) -> Dict[str, Set[str]]:
    """{value key: {fact keys stating it}} over the categorical facts - the
    package scalars and every schedule row's column of the same name."""
    out: Dict[str, Set[str]] = {}
    wanted = set(_CATEGORICAL_FACTS)
    for fk, raw in (facts or {}).items():
        if not isinstance(fk, str) or fk.startswith("_"):
            continue
        v = _fv(facts, fk)
        if fk in wanted and not isinstance(v, (list, dict)):
            k = _categorical_value(v)
            if k:
                out.setdefault(k, set()).add(fk)
        if isinstance(v, list):
            for row in v:
                if not isinstance(row, dict):
                    continue
                for sk, sv in row.items():
                    if sk in wanted and not isinstance(sv, (list, dict)):
                        k = _categorical_value(sv)
                        if k:
                            out.setdefault(k, set()).add(sk)
    return out


def _own_fact_keys(field: str) -> Set[str]:
    """The fact(s) the deterministic layer binds this box to: its first
    `_ACORD_FIELD_RULES` pattern and its schedule column."""
    out: Set[str] = set()
    try:
        from services.pdf_service import _ACORD_FIELD_RULES, _SCHEDULE_REGISTRY
    except Exception:                                       # pragma: no cover
        return out
    for pattern, fact_key in _ACORD_FIELD_RULES:
        if pattern in field:
            if fact_key and not str(fact_key).startswith("_"):
                out.add(str(fact_key))
            break
    base = re.sub(r"_[A-N]\d?$", "", field)
    sched = _SCHEDULE_REGISTRY.get(base)
    if sched is not None and getattr(sched, "sub_key", None):
        out.add(str(sched.sub_key))
    return out


@lru_cache(maxsize=64)
def _home_row_groups(fact_key: str) -> frozenset:
    """The ROW GROUPS of the boxes a rule or a schedule binds `fact_key` to -
    a box name minus its leaf, kept only when it is a real group of two or
    more segments ("CommercialProperty_Premises" for the valuation code; a
    bare section like "GeneralLiability" is a whole form section, not a row)."""
    out: set = set()
    try:
        from services.pdf_service import _ACORD_FIELD_RULES, _SCHEDULE_REGISTRY
    except Exception:                                       # pragma: no cover
        return frozenset()
    names = [p for p, fk in _ACORD_FIELD_RULES if fk == fact_key]
    names += [b for b, d in _SCHEDULE_REGISTRY.items()
              if getattr(d, "sub_key", None) == fact_key]
    for name in names:
        segs = [s for s in str(name).split("_") if s]
        if len(segs) >= 3:
            out.add("_".join(segs[:-1]))
    return frozenset(out)


# The nouns ACORD names a property RISK by. A free-text box whose name names
# only the risk ("CommercialStructure_Building_SublocationDescription": "This
# describes the particular sublocation in a manner sufficient to distinguish
# it", e.g. "3 story blue structure") describes the risk itself, so any of the
# risk's own attributes may describe it - measured on the corpus, a building
# told apart by its occupancy. A box naming a TOPIC (fire protection, exposure,
# security, interest) describes that topic and nothing else.
_RISK_NOUNS = frozenset({"building", "structure", "sublocation", "location", "premises"})
_DESCRIPTION_WORDS = frozenset({"commercial", "description", "remark", "remarks", "text",
                                "information", "detail", "details"})
_FREE_TEXT_RE = re.compile(r"^\s*enter text\s*:", re.I)


def _describes_the_risk_itself(field: str, schema: dict) -> bool:
    if not _FREE_TEXT_RE.match(_tooltip(field, schema)):
        return False
    words = [w for w in _words(re.sub(r"_[A-N]\d?$", "", field).replace("_", " "))
             if w not in _DESCRIPTION_WORDS]
    return bool(words) and all(_singular(w) in _RISK_NOUNS for w in words)


def _box_takes_fact(field: str, schema: dict, fact_key: str, value_key: str,
                    own_words: Set[str]) -> bool:
    """Can this box legitimately hold `fact_key`'s value? Measured on the
    corpus, a box takes it when

      * the box's name or ACORD's own description of it names the fact's
        subject ("Construction_RoofMaterialCode" names construction; "the
        description of the other legal entity" names the entity);
      * ACORD lists the value among the box's own options ("AN - Annual",
        "B - Building" - a value the box's instruction offers is never
        another box's);
      * it is a free-text box of the fact's own ROW ("FORMS AND CONDITIONS TO
        APPLY" beside the premises row's valuation: an "AGREED VALUE" there is
        a condition of that row, which the owner verified on the live run);
      * it is a free-text description of the property risk itself."""
    concept = _concept_words(fact_key)
    name_w, tip_w = _box_text_words(field, schema)
    if any(_same_word(c, w) for c in concept for w in list(name_w) + list(tip_w) + list(own_words)):
        return True
    tip_key = f" {_key(_tooltip(field, schema))} "
    if f" {value_key} " in tip_key:
        return True
    if _FREE_TEXT_RE.match(_tooltip(field, schema)):
        group = "_".join(re.sub(r"_[A-N]\d?$", "", field).split("_")[:-1])
        if group and group in _home_row_groups(fact_key):
            return True
    return _describes_the_risk_itself(field, schema)


def _other_fact_value(mapped: dict, schema: dict, facts: dict, ai: Iterable[str]) -> Dict[str, str]:
    """(a) An AI value equal to the package's stated value of a categorical
    fact, in a box that cannot take that fact, is that fact's value borrowed.

    "FRAME" is the building's construction; a fire-protection box ("sprinklers,
    standpipes, chemical systems") names no construction, is no construction
    fact's box, and does not offer "Frame" - so FRAME there is borrowed.

    Legitimate equalities are excluded STRUCTURALLY, measured on the corpus:
    a value ACORD lists among the box's own options ("Annual" in the payment
    plan box beside an annual audit; "Building" in the subject-of-insurance
    box), a box whose name or tooltip names the fact's subject (the other
    legal entity's description takes an entity type), the fact's own box.
    Checkboxes are another guard's (Guard 3); a value with a digit is never a
    category here."""
    values = _categorical_values(facts)
    out: Dict[str, str] = {}
    if not values:
        return out
    for field in sorted(ai):
        val = mapped.get(field)
        if val is None or _is_checkbox(field, schema):
            continue
        vk = _categorical_value(val)
        if not vk or vk not in values:
            continue
        stated_by = values[vk]
        own = _own_fact_keys(field)
        own_words = {w for fk in own for w in _concept_words(fk)}
        if any(fk in own for fk in stated_by):
            continue
        if any(_box_takes_fact(field, schema, fk, vk, own_words) for fk in stated_by):
            continue
        names = "/".join(sorted(stated_by))
        out[field] = (f"{R_OTHER_FACT}: {str(val)[:30]!r} is the package's {names}, "
                      "and this box is not about that")
    return out


# ══ (b) A SHORT COUNT WITH NO LABELLED WITNESS ════════════════════════════════
# `pdf_service._drop_unstated_counts` judges every count box whose ACORD
# tooltip says what it counts ("The number of employees ..."). Some count
# boxes say it only in their NAME: ACORD 130's HIGHEST FLOOR ("The highest
# floor of the physical location", `Location_HighestFloorCount`), ACORD 126's
# EXPECTED LIFE ("The anticipated number of months ..."). Nothing read those,
# so a 1-3 character AI answer - too short to verify by its presence, "1" is
# printed everywhere - went out as the LOC number did on Choice Electric.
#
# Such a count is kept only beside its own noun: a fact about the same thing,
# a verified declarations entry naming it, or the documents printing the
# number within a few words of it - the existing count guard's own witnesses
# (`_count_held_by_a_fact`, `_count_is_stated`). A MEASUREMENT (miles to the
# fire station, feet to the hydrant) is not a count, as there.
_COUNT_QUALIFIERS = frozenset({
    "highest", "lowest", "maximum", "minimum", "average", "total", "expected",
    "estimated", "anticipated", "actual", "number", "count", "code", "indicator",
})
# A floor is a storey: ACORD's own tooltip for `Construction_StoreyCount` reads
# "The number of stories or floors", so a "2 STORIES" print witnesses a highest
# floor of 2.
_COUNT_NOUN_EQUIVALENTS: Dict[str, Tuple[str, ...]] = {
    "floor": ("story", "storey"),
    "story": ("floor", "storey"),
    "storey": ("floor", "story"),
}
_SHORT_COUNT_RE = re.compile(r"^\s*\d{1,3}\s*$")


def _name_declared_count_nouns(field: str, schema: dict) -> Set[str]:
    """The nouns of a count box whose NAME declares the count (its last
    segment ends "Count") and whose tooltip the existing count reader cannot
    read; empty for every other box, and for a measurement."""
    try:
        from services.pdf_service import (_count_subject_words, _COUNT_TOOLTIP_RE,
                                          _COUNT_UNIT_WORDS, _count_word)
    except Exception:                                       # pragma: no cover
        return set()
    tip = _tooltip(field, schema)
    if not _COUNT_TOOLTIP_RE.match(tip) or _count_subject_words(tip):
        return set()                     # not a number box, or already judged
    leaf = re.sub(r"_[A-N]\d?$", "", field).split("_")[-1]
    if not leaf.endswith("Count"):
        return set()
    words = [_count_word(w) for w in _words(leaf)]
    if set(words) & {_count_word(u) for u in _COUNT_UNIT_WORDS} or "distance" in words:
        return set()                     # a measurement, not a count
    nouns = {w for w in words if w not in _COUNT_QUALIFIERS and len(w) >= 3}
    for n in list(nouns):
        nouns.update(_COUNT_NOUN_EQUIVALENTS.get(n, ()))
        # The thing a verb-noun counts: "SEATING capacity" is printed "5 SEATS".
        if n.endswith("ing") and len(n) > 5:
            nouns.add(n[:-3])
    return nouns


def _entry_pairs_count(number: int, nouns: Set[str], facts: dict) -> bool:
    """A verified declarations entry names the counted thing and states the
    number ("Stories: 2", "Number of Floors: 3")."""
    entries = _fv(facts, "dec_page_entries")
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            continue
        text_words = {_singular(w) for w in _words(f"{e.get('label') or ''} {e.get('value') or ''}")}
        if not (text_words & nouns):
            continue
        nums = re.findall(r"(?<![\d.,])\d{1,3}(?![\d,])", str(e.get("value") or ""))
        if str(number) in {str(int(n)) for n in nums}:
            return True
    return False


def _short_count_without_witness(mapped: dict, schema: dict, facts: dict, raw_text: str,
                                 ai: Iterable[str], cache: dict) -> Dict[str, str]:
    """(b) See the block comment above."""
    out: Dict[str, str] = {}
    # NO INDEX, NO OPINION. The declarations index is one of this rule's
    # WITNESSES ("Stories: 2" keeps a 2), and production purges it after
    # generation (PURGE_DEC_INDEX_AFTER_GENERATION) - a form stamped later
    # (form_addition) would lose a witness and could refuse a count the index
    # alone backed. Absent index (purged, or never recorded) = the rule stands
    # down; an index that exists but is empty is a real reading and is used.
    if not isinstance(_fv(facts, "dec_page_entries"), list):
        return out
    try:
        from services.pdf_service import (_count_held_by_a_fact, _count_is_stated,
                                          _document_number_tokens)
    except Exception:                                       # pragma: no cover
        return out
    for field in sorted(ai):
        val = mapped.get(field)
        if val is None or not _SHORT_COUNT_RE.match(str(val)):
            continue
        nouns = _name_declared_count_nouns(field, schema)
        if not nouns:
            continue
        number = int(str(val).strip())
        if number == 0:
            continue                     # a zero count is the meaning gate's
        if _count_held_by_a_fact(number, nouns, facts) or _entry_pairs_count(number, nouns, facts):
            continue
        if raw_text:
            if "tokens" not in cache:
                cache["tokens"] = _document_number_tokens(raw_text)
            if _count_is_stated(number, nouns, cache["tokens"]):
                continue
        out[field] = (f"{R_COUNT}: {str(val).strip()!r} - nothing prints it beside "
                      f"{'/'.join(sorted(nouns))}")
    return out


# ══ (c) A PREMIUM-LINE AMOUNT IN A COVERAGE-AMOUNT BOX ════════════════════════
# The numeric meaning gate reads what an amount IS from the declarations
# entries and the facts. A rating line is neither: "CO 0930 Waiver of Our
# Right to Recover from Others Endorsement-Blanket 0.0200 500.00" is a premium
# by its SHAPE - a rate column, then the premium column at the end of the line
# - and no entry or fact records it. Choice Electric's ACORD 130 printed that
# $500 as the WC DEDUCTIBLE.
#
# The occurrence's own TEXT LINE is the context. The amount is a premium on a
# line when it is the line's LAST amount and either a rate (three or more
# decimals - "0.0200", "1.8800") sits between it and the nearest category word
# before it, or that nearest word is premium wording (the gate's own premium
# vocabulary, with charge / surcharge / credit / fee: "TOTAL INLAND MARINE
# PREMIUM $ 300.00", "Premium Discount 0.0605 -1,802.00"). A limit named
# closer to the amount than a premium word ("Premium for Limit of
# $1,000,000") is a limit; an amount followed by more amounts is a column of
# exposures or limits.
#
# An occurrence printed for ANOTHER coverage line - the line names it ("CRIME
# AND FIDELITY COVERAGE PART $ 500.00"), or a verified declarations entry of
# that line prints it there - says nothing about this box's line, so it is
# set aside: the $500 PROPERTY deductible on the package dec does not make the
# WC rating line's $500 a WC deductible. The amount is refused only when every
# remaining occurrence is a premium line - one unexplained occurrence and the
# box keeps its value.
_COVERAGE_AMOUNT_CATEGORIES = frozenset({"deductible", "limit", "value"})
_PREMIUM_EXTRA_WORDS = frozenset({"charge", "charges", "surcharge", "surcharges",
                                  "credit", "credits", "fee", "fees"})
_AMOUNT_TOKEN_RE = re.compile(r"(?<![\w.,])(-?)\$?\s?(\d[\d,]*(?:\.\d+)?)(?!\d)(?![,.]\d)(?![A-Za-z])")
_RATE_DECIMALS = 3


def _amount_of(text: Any) -> Optional[Decimal]:
    s = str(text or "").strip()
    m = re.fullmatch(r"\(?\s*-?\$?\s*(\d[\d,]*(?:\.\d+)?)\s*\)?", s)
    if not m:
        return None
    try:
        return Decimal(m.group(1).replace(",", ""))
    except (InvalidOperation, ValueError):                  # pragma: no cover
        return None


def _line_tokens(line: str) -> List[Tuple[int, int, Decimal, str]]:
    """(start, end, value, digits) of every amount-shaped token on a line;
    a zero-padded code ("0930", "001") is an identifier, not an amount."""
    out = []
    for m in _AMOUNT_TOKEN_RE.finditer(line):
        digits = m.group(2)
        if re.fullmatch(r"0\d+", digits):
            continue
        try:
            out.append((m.start(2), m.end(2), Decimal(digits.replace(",", "")), digits))
        except (InvalidOperation, ValueError):              # pragma: no cover
            continue
    return out


def _is_rate(digits: str) -> bool:
    if "." not in digits:
        return False
    whole, frac = digits.split(".", 1)
    try:
        return len(frac) >= _RATE_DECIMALS and Decimal(digits.replace(",", "")) < 100
    except (InvalidOperation, ValueError):                  # pragma: no cover
        return False


def _category_vocab() -> Dict[str, str]:
    """{word: category} - the meaning gate's vocabulary, with the charge words
    as premium."""
    vocab: Dict[str, str] = {}
    try:
        from services.pdf_service import _AMOUNT_CATEGORY_TOKENS
        for cat, words in _AMOUNT_CATEGORY_TOKENS.items():
            for w in words:
                vocab[w] = cat
    except Exception:                                       # pragma: no cover
        vocab.update({"premium": "premium", "prem": "premium"})
    for w in _PREMIUM_EXTRA_WORDS:
        vocab[w] = "premium"
    return vocab


def _is_premium_occurrence(line: str, tokens, idx: int, vocab: Dict[str, str]) -> bool:
    """See the block comment: the line's last amount, after a rate or after
    premium wording that is the nearest category word before it."""
    if idx != len(tokens) - 1:
        return False
    start = tokens[idx][0]
    prior = line[:start]
    nearest_pos, nearest_cat = -1, None
    for m in re.finditer(r"[A-Za-z]+", prior):
        cat = vocab.get(m.group(0).lower())
        if cat:
            nearest_pos, nearest_cat = m.end(), cat
    rate_after_word = any(_is_rate(t[3]) and t[0] >= nearest_pos for t in tokens[:idx])
    if rate_after_word:
        return True
    return nearest_cat == "premium"


def _occurrence_line_family(line: str, value: Decimal, entries) -> Optional[str]:
    """The coverage line an occurrence is printed for: the line's own words,
    else a verified declarations entry of a line whose value is printed on
    this text line and states this amount. None when nothing places it."""
    try:
        from services.lob_canon import canon_line
    except Exception:                                       # pragma: no cover
        return None
    words = re.sub(r"[\d$,.%()|:/-]+", " ", line)
    fam = canon_line(words) if re.search(r"[A-Za-z]{3}", words) else None
    if fam:
        return fam
    line_key = f" {_key(line)} "
    for e in entries:
        ev = str(e.get("value") or "")
        if not ev.strip() or f" {_key(ev)} " not in line_key:
            continue
        if not any(t[2] == value for t in _line_tokens(ev)):
            continue
        # An entry whose value is the bare amount ("$ 500.00") is printed on
        # this line only if its LABEL is too - every other line printing 500.00
        # is somebody else's.
        if not re.search(r"[A-Za-z]{3}", ev):
            lab = _key(e.get("label"))
            if not lab or f" {lab} " not in line_key:
                continue
        try:
            from services.pdf_service import _entry_families
            fams = _entry_families(e)
        except Exception:                                   # pragma: no cover
            fams = set()
        if len(fams) == 1:
            return next(iter(fams))
    return None


def _premium_line_amount(mapped: dict, schema: dict, facts: dict, raw_text: str,
                         ai: Iterable[str], form_id: str, cache: dict) -> Dict[str, str]:
    """(c) See the block comment above."""
    out: Dict[str, str] = {}
    if not raw_text:
        return out
    try:
        from services.pdf_service import _amount_category, _CAMEL_SPLIT_RE, _box_line_family
    except Exception:                                       # pragma: no cover
        return out
    vocab = cache.setdefault("vocab", _category_vocab())
    entries = [e for e in (_fv(facts, "dec_page_entries") or []) if isinstance(e, dict)] \
        if isinstance(_fv(facts, "dec_page_entries"), list) else []
    for field in sorted(ai):
        val = mapped.get(field)
        amt = _amount_of(val)
        if amt is None or amt == 0:
            continue
        tip = _tooltip(field, schema)
        if not re.match(r"\s*enter (amount|limit|deductible)", tip, re.I):
            continue
        cat = _amount_category(_CAMEL_SPLIT_RE.sub(" ", field)) or _amount_category(tip)
        if cat not in _COVERAGE_AMOUNT_CATEGORIES:
            continue
        if "occ" not in cache:
            # Every amount of the documents, indexed once per form:
            # {amount: [(line, its tokens, token index)]}.
            occ: Dict[Decimal, list] = {}
            for line in str(raw_text).splitlines():
                if not re.search(r"\d", line):
                    continue
                toks = _line_tokens(line)
                for i, t in enumerate(toks):
                    occ.setdefault(t[2], []).append((line, toks, i))
            cache["occ"] = occ
        box_line, _own = _box_line_family(field, form_id)
        relevant: List[bool] = []
        for line, toks, i in cache["occ"].get(amt, ()):
            fam = _occurrence_line_family(line, amt, entries)
            if box_line and fam and fam != box_line:
                continue                     # printed for another line
            relevant.append(_is_premium_occurrence(line, toks, i, vocab))
        if relevant and all(relevant):
            out[field] = (f"{R_PREMIUM}: {str(val).strip()!r} is printed only as a premium "
                          f"on a rating line, never as a {cat}")
    return out


# ══ (e) A PRODUCER ROLE THE ACCOUNT DOES NOT STATE ════════════════════════════
# The producer block is the submitting agency's, and its facts come from the
# login (`extraction_service._route_producer_party`): the agency name, the
# contact person, the contact's e-mail and phone ("Contact Phone - printed as
# the producer phone"), the agency address. Nothing states a CUSTOMER SERVICE
# REPRESENTATIVE, a CELL phone, a customer id, an NPN or a licence number.
#
# The owner's run printed the contact's name as the CSR and the contact's
# phone as the CELL phone on ACORD 130 (and stored runs put the APPLICANT's
# contact there). Decision: wrong role. A box whose role the profile does not
# state may not hold a copy of a role it does state - unless the documents
# print that value under the box's own role ("CSR: ...", "Cell: ...").
_PRODUCER_STATED_FACTS: Tuple[str, ...] = (
    "producer_name", "producer_contact_name", "producer_contact_phone",
    "producer_contact_email", "producer_fax",
)
# Another party's contact the model has copied into the producer block.
_APPLICANT_CONTACT_FACTS: Tuple[str, ...] = ("contact_name", "contact_phone", "contact_email")
_ROLE_GENERIC_WORDS = frozenset({
    "producer", "full", "name", "number", "contact", "person", "identifier",
    "phone", "address", "email", "the", "of",
})
_ROLE_SYNONYMS: Dict[str, Tuple[str, ...]] = {
    "cell": ("mobile", "cellular"),
    "customer": ("csr",),
    "representative": ("csr", "rep"),
    "national": ("npn",),
}


def _contact_key(value: Any) -> str:
    """Identity of a name, an e-mail or a phone: a phone by its last ten digits
    (the account's "7983789751" is the form's "798-378-9751")."""
    s = str(value or "").strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 7 and not re.search(r"[A-Za-z]{2}", s):
        return "tel:" + digits[-10:]
    return _key(s)


def _role_words(field: str) -> Set[str]:
    base = re.sub(r"_[A-N]\d?$", "", field)
    words = {w for w in _words(base.replace("_", " ")) if w not in _ROLE_GENERIC_WORDS}
    for w in list(words):
        words.update(_ROLE_SYNONYMS.get(w, ()))
    return words


def _labelled_in_text(value: Any, role: Set[str], raw_text: str) -> bool:
    """The documents print `value` on a line that names the box's role."""
    if not raw_text or not role:
        return False
    vk = _contact_key(value)
    for line in str(raw_text).splitlines():
        if vk.startswith("tel:"):
            if vk[4:] not in re.sub(r"\D", "", line):
                continue
        elif vk not in _key(line):
            continue
        if {w for w in _words(line)} & role:
            return True
    return False


def _producer_role_copy(mapped: dict, schema: dict, facts: dict, raw_text: str,
                        ai: Iterable[str]) -> Dict[str, str]:
    """(e) See the block comment above."""
    out: Dict[str, str] = {}
    stated: Dict[str, str] = {}
    for fk in _PRODUCER_STATED_FACTS + _APPLICANT_CONTACT_FACTS:
        v = _fv(facts, fk)
        if v is None or isinstance(v, (list, dict)) or not str(v).strip():
            continue
        k = _contact_key(v)
        if k and len(k.replace("tel:", "")) >= 3:
            stated.setdefault(k, fk)
    if not stated:
        return out
    for field in sorted(ai):
        if not field.startswith("Producer_") or "Signature" in field:
            continue
        val = mapped.get(field)
        if val is None or not str(val).strip():
            continue
        if _own_fact_keys(field):
            continue                     # a box with its own fact: another rule's
        holder = stated.get(_contact_key(val))
        if not holder:
            continue
        if _labelled_in_text(val, _role_words(field), raw_text):
            continue
        out[field] = (f"{R_PRODUCER_ROLE}: the {holder.replace('_', ' ')}, a role this "
                      "box does not hold")
    return out


# ══ (e2) THE APPLICANT'S CONTACT IN A ROLE NOBODY STATED (14 Oct 2026) ════════
# The same rule for the applicant's side of the form. ACORD 130 asks for an
# ACCOUNTING, a CLAIMS and an INSPECTION contact - "an individual under the
# insured's employment" for each role - and the live Choice Electric runs
# printed the one contact the producer typed ("Dana Whitfield", her phone)
# in all three; 13 stored packages did the same with a document's general
# "Contact:" line. A role box (its name qualifies the contact: Accounting /
# Claim / Inspection ...) may hold the general contact's name, phone or
# e-mail only when a document prints that value on a line that names the
# role, or under a heading naming it a line or two above ("Accounting Contact
# Name: Priya Raman" stays). A different person the AI found is not this
# rule's question. Measured over the stored corpus: 122 boxes on 17 packages,
# none with a role word within three lines of the value.
_GENERAL_CONTACT_FACTS: Tuple[str, ...] = ("contact_name", "contact_phone", "contact_email")
_ROLE_HEADING_LINES = 2          # "ACCOUNTING CONTACT" above "Name: ..." / "Phone: ..."


def _labelled_in_block(value: Any, role: Set[str], raw_text: str) -> bool:
    """`_labelled_in_text` with the role allowed on a heading line just above
    the value (a block laid out "ACCOUNTING CONTACT / Name: X / Phone: Y")."""
    if not raw_text or not role:
        return False
    vk = _contact_key(value)
    lines = str(raw_text).splitlines()
    for i, line in enumerate(lines):
        if vk.startswith("tel:"):
            if vk[4:] not in re.sub(r"\D", "", line):
                continue
        elif vk not in _key(line):
            continue
        block = lines[max(0, i - _ROLE_HEADING_LINES):i + 1]
        if any(set(_words(b)) & role for b in block):
            return True
    return False


_ROLE_CONTACT_BOX_RE = re.compile(r"^(?P<who>[A-Za-z]+)_(?P<role>[A-Z][a-z]+)Contact_\w+_[A-N]$")
R_CONTACT_ROLE = "CONTACT_ROLE_NOT_STATED"


def _applicant_contact_role_copy(mapped: dict, facts: dict, raw_text: str,
                                 ai: Iterable[str]) -> Dict[str, str]:
    """(e2) See the block comment above."""
    out: Dict[str, str] = {}
    general: Dict[str, str] = {}
    for fk in _GENERAL_CONTACT_FACTS:
        v = _fv(facts, fk)
        if v is None or isinstance(v, (list, dict)) or not str(v).strip():
            continue
        k = _contact_key(v)
        if k and len(k.replace("tel:", "")) >= 3:
            general.setdefault(k, fk)
    if not general:
        return out
    for field in sorted(ai):
        m = _ROLE_CONTACT_BOX_RE.match(field or "")
        if not m or m.group("who").startswith("Producer"):
            continue
        val = mapped.get(field)
        if val is None or not str(val).strip():
            continue
        holder = general.get(_contact_key(val))
        if not holder:
            continue
        role = {m.group("role").lower()}
        role |= {f"{w}s" for w in role}
        if _labelled_in_block(val, role, raw_text):
            continue
        out[field] = (f"{R_CONTACT_ROLE}: the general {holder.replace('_', ' ')}, never stated as "
                      f"the {m.group('role').lower()} contact")
    return out


# ══ (d) BINDER BOXES ══════════════════════════════════════════════════════════
# ACORD 130 prints "BOUND (Give Date and/or Attach Copy)": the date the binder
# took effect. On a package with no binder it is a decision the producer makes
# when the coverage is bound - the same owned blank as the STATUS OF
# TRANSACTION ticks beside it (`pdf_service._resolve_policy_status`). The
# owner's run printed the expiring term's 01/01/2025 there; the corpus has 13
# more AI binder dates, none on a package with a binder document.
_BINDER_BOX_RE = re.compile(r"^Binder_\w+_[A-N]$")


def is_binder_box(field_name: str) -> bool:
    return bool(_BINDER_BOX_RE.match(str(field_name or "")))


def package_has_binder(facts: Any) -> bool:
    """A binder-type document is among the package's ACTIVE documents (the
    merge's `_package_doc_types` flag, or a binder as the primary document)."""
    if not isinstance(facts, dict):
        return False
    types = _fv(facts, "_package_doc_types")
    if isinstance(types, (list, tuple, set)) and any(
            str(t or "").strip().lower() == "binder" for t in types):
        return True
    return str(_fv(facts, "_doc_type") or "").strip().lower() == "binder"


def binder_box_owned_blank(field_name: str, facts: Any) -> bool:
    """True when this is a binder box the package cannot answer: an owned
    blank (the model is not asked). A package with a binder document leaves
    the box to the ordinary paths, and a person's own entry is never a
    stamping question."""
    return is_binder_box(field_name) and not package_has_binder(facts)


# ══ The one entry point ═══════════════════════════════════════════════════════

def drop_role_mismatches(mapped: dict, schema: dict, facts: dict, raw_text: str,
                         gpt_filled_set: Optional[set], form_id: str = "") -> Dict[str, str]:
    """Blank every AI value the rules above refuse. Returns
    {field: "CODE: reason"}. Never raises on bad input; a rule that fails is
    skipped and logged."""
    out: Dict[str, str] = {}
    if not gpt_filled_set or not isinstance(mapped, dict):
        return out
    schema = schema if isinstance(schema, dict) else {}
    facts = facts if isinstance(facts, dict) else {}
    # ACORD 141 / 160 are frozen (owner, 14 Sep 2026) - no new guard acts on them.
    if str(form_id or facts.get("_form_id") or "").split("__", 1)[0] in ("ACORD_141", "ACORD_160"):
        return out
    ai = [f for f in gpt_filled_set
          if isinstance(f, str) and mapped.get(f) is not None and str(mapped.get(f)).strip()]
    if not ai:
        return out
    cache: dict = {}
    rules = (
        ("other_fact", lambda: _other_fact_value(mapped, schema, facts, ai)),
        ("short_count", lambda: _short_count_without_witness(mapped, schema, facts,
                                                             raw_text or "", ai, cache)),
        ("premium_line", lambda: _premium_line_amount(mapped, schema, facts, raw_text or "",
                                                      ai, form_id or str(facts.get("_form_id") or ""),
                                                      cache)),
        ("producer_role", lambda: _producer_role_copy(mapped, schema, facts, raw_text or "", ai)),
        ("contact_role", lambda: _applicant_contact_role_copy(mapped, facts, raw_text or "", ai)),
    )
    for name, rule in rules:
        try:
            for field, why in rule().items():
                out.setdefault(field, why)
        except Exception as ex:                             # noqa: BLE001
            logger.warning("ai_role_guards %s skipped (form=%s): %s", name, form_id, ex)
    for field, why in out.items():
        mapped[field] = None
        code, _, detail = why.partition(":")
        logger.info("gpt_fill DROP_%s: field=%s -%s", code, field, detail)
    return out
