"""Covered-auto symbol table and reasoning helpers.

WHAT A SYMBOL IS
----------------
A commercial auto policy never writes out "this coverage applies to these
vehicles". It prints a NUMBER next to each coverage line, and that number is a
defined term meaning "which autos this coverage applies to":

    1  any auto (owned, hired, borrowed, employees' - everything)
    2  owned autos only
    7  specifically described autos (the ones on the vehicle schedule)
    8  hired autos only
    9  non-owned autos only

So "Liability 1 / Comprehensive 7 / Collision 7" means *liability protects any
vehicle the business touches; physical damage only pays for the scheduled
trucks*. One digit, a very large coverage consequence.

Trucking, motor-carrier and garage/dealer policies use their own numbered sets
for the same idea (41-50, 61-71, 21-31).

WHY THIS FILE EXISTS
--------------------
The definitions below are not invented here. They are ACORD's own wording,
lifted verbatim from the `/TU` tooltips of the real symbol checkboxes in
`forms_schemas/ACORD_137_CA|CO_schema.json` (business auto / truckers / motor
carrier) and `forms_schemas/ACORD_138_CA|CO_schema.json` (garage and dealers).
`tests/test_auto_symbols.py::test_every_symbol_binds_to_a_live_acord_field`
re-reads those schemas and fails the build if any row here stops matching a
real field or its real tooltip - so the table can never drift from ACORD.

Before this module, those 37 definitions existed ONLY as tooltip strings handed
to the gap-fill LLM. No code ever read them. Meanwhile
`cross_form_validator` checked five fact keys that nothing in the codebase ever
wrote (`hired_auto_symbol`, `non_owned_symbol`,
`auto_physical_damage_comp_symbol`, `auto_physical_damage_coll_symbol`,
`drive_other_car_symbol`), so its symbol warnings fired on every auto
submission regardless of what the policy actually said.

DESIGN RULES (do not weaken these)
----------------------------------
1. Deterministic only. A covered-auto symbol is a coverage designation with
   legal effect; an LLM inventing one is exactly the failure the standing
   "blank over wrong" rule exists to prevent. Nothing here guesses.
2. Silence on the unknown. If a document carries a symbol this table does not
   define (ISO 5 and 19 are real and are NOT printed on the ACORD grid, and
   carriers may use company-unique symbols), every reasoning helper declines to
   draw a conclusion rather than reporting a false gap.
3. The numbers self-identify their family - the four ACORD sets do not overlap -
   so family detection never needs a keyword guess.
"""

from __future__ import annotations

import re
from typing import Dict, FrozenSet, Iterable, List, NamedTuple, Optional

# ── Exposure vocabulary ───────────────────────────────────────────────────────
# What a symbol's covered-autos designation INCLUDES. Deliberately small: these
# are the only distinctions any validator in this codebase reasons about.

OWNED             = "owned"
HIRED             = "hired"
NONOWNED          = "nonowned"
SCHEDULED         = "scheduled"
PRIVATE_PASSENGER = "private_passenger"
TRAILER_INTERCHANGE = "trailer_interchange"
CUSTOMER_AUTOS    = "customer_autos"
CONSIGNMENT       = "consignment"

# ── Families ──────────────────────────────────────────────────────────────────

BUSINESS_AUTO = "business_auto"
TRUCKERS      = "truckers"
MOTOR_CARRIER = "motor_carrier"
GARAGE        = "garage"

FAMILY_LABEL: Dict[str, str] = {
    BUSINESS_AUTO: "Business Auto",
    TRUCKERS:      "Truckers",
    MOTOR_CARRIER: "Motor Carrier",
    GARAGE:        "Garage and Dealers",
}

# ACORD field-name prefix for each family's checkbox grid. The full indicator
# field is  <prefix><Word>Indicator_<row>  e.g.
# "Vehicle_BusinessAutoSymbol_OneIndicator_A".
FAMILY_FIELD_PREFIX: Dict[str, str] = {
    BUSINESS_AUTO: "Vehicle_BusinessAutoSymbol_",
    TRUCKERS:      "Vehicle_TruckersSymbol_",
    MOTOR_CARRIER: "Vehicle_MotorCarrierSymbol_",
    GARAGE:        "Vehicle_GarageAndDealersSymbol_",
}

# Which forms carry each family's grid (audited against the real schemas).
FAMILY_FORMS: Dict[str, FrozenSet[str]] = {
    BUSINESS_AUTO: frozenset({"ACORD_137_CA", "ACORD_137_CO"}),
    TRUCKERS:      frozenset({"ACORD_137_CA", "ACORD_137_CO"}),
    MOTOR_CARRIER: frozenset({"ACORD_137_CA", "ACORD_137_CO"}),
    GARAGE:        frozenset({"ACORD_138_CA", "ACORD_138_CO", "ACORD_160"}),
}


class SymbolDef(NamedTuple):
    number: int
    family: str
    word: str          # ACORD field-name word ("One", "TwentySeven", ...)
    description: str   # ACORD's own tooltip wording, trimmed
    covers: FrozenSet[str]


def _d(number, family, word, description, *covers) -> SymbolDef:
    return SymbolDef(number, family, word, description, frozenset(covers))


# ── The table ─────────────────────────────────────────────────────────────────
# Descriptions are ACORD's tooltip text with the leading
# "Check the box (if applicable): Indicates " boilerplate removed.

_ALL: List[SymbolDef] = [
    # Business Auto (ACORD 137 CA/CO). ACORD prints 1,2,3,4,6,7,8,9 plus an
    # "Other symbol" free-text box; ISO symbols 5 and 19 live in that box and
    # are deliberately absent here - see design rule 2.
    _d(1, BUSINESS_AUTO, "One",   "any auto is covered",
       OWNED, HIRED, NONOWNED, SCHEDULED, PRIVATE_PASSENGER),
    _d(2, BUSINESS_AUTO, "Two",   "owned autos only are covered",
       OWNED, SCHEDULED, PRIVATE_PASSENGER),
    _d(3, BUSINESS_AUTO, "Three", "owned private passenger autos only are covered",
       OWNED, PRIVATE_PASSENGER),
    _d(4, BUSINESS_AUTO, "Four",  "owned autos other than private passenger autos only are covered",
       OWNED),
    _d(6, BUSINESS_AUTO, "Six",   "owned autos subject to a compulsory uninsured motorists law are covered",
       OWNED),
    _d(7, BUSINESS_AUTO, "Seven", "specifically described autos are covered",
       SCHEDULED),
    _d(8, BUSINESS_AUTO, "Eight", "hired autos only are covered",
       HIRED),
    _d(9, BUSINESS_AUTO, "Nine",  "non-owned autos only are covered",
       NONOWNED),

    # Garage and Dealers (ACORD 138 CA/CO, ACORD 160).
    _d(21, GARAGE, "TwentyOne",   "any auto is covered",
       OWNED, HIRED, NONOWNED, SCHEDULED, PRIVATE_PASSENGER),
    _d(22, GARAGE, "TwentyTwo",   "owned autos only are covered",
       OWNED, SCHEDULED, PRIVATE_PASSENGER),
    _d(23, GARAGE, "TwentyThree", "owned private passenger autos only are covered",
       OWNED, PRIVATE_PASSENGER),
    _d(24, GARAGE, "TwentyFour",  "owned autos other than private passenger autos only are covered",
       OWNED),
    _d(26, GARAGE, "TwentySix",   "owned autos subject to a compulsory uninsured motorists law are covered",
       OWNED),
    _d(27, GARAGE, "TwentySeven", "specifically described autos are covered",
       SCHEDULED),
    _d(28, GARAGE, "TwentyEight", "hired autos only are covered",
       HIRED),
    _d(29, GARAGE, "TwentyNine",  "non-owned autos used in garage business are covered",
       NONOWNED),
    _d(30, GARAGE, "Thirty",      "autos left with you for service, repair, storage or safekeeping are covered",
       CUSTOMER_AUTOS),
    _d(31, GARAGE, "ThirtyOne",   "autos on consignment and dealer autos are covered",
       CONSIGNMENT),

    # Truckers (ACORD 137 CA/CO).
    _d(41, TRUCKERS, "FortyOne",   "any auto is covered",
       OWNED, HIRED, NONOWNED, SCHEDULED),
    _d(42, TRUCKERS, "FortyTwo",   "owned autos only are covered",
       OWNED, SCHEDULED),
    _d(43, TRUCKERS, "FortyThree", "owned commercial autos only are covered",
       OWNED),
    _d(45, TRUCKERS, "FortyFive",  "owned autos subject to a compulsory uninsured motorist law are covered",
       OWNED),
    _d(46, TRUCKERS, "FortySix",   "specifically described autos are covered",
       SCHEDULED),
    _d(47, TRUCKERS, "FortySeven", "hired autos only are covered",
       HIRED),
    _d(48, TRUCKERS, "FortyEight", "trailers in your possession under a trailer interchange agreement are covered",
       TRAILER_INTERCHANGE),
    _d(49, TRUCKERS, "FortyNine",  "your trailers in the possession of another trucker under a trailer interchange agreement are covered",
       TRAILER_INTERCHANGE),
    _d(50, TRUCKERS, "Fifty",      "non-owned autos only are covered",
       NONOWNED),

    # Motor Carrier (ACORD 137 CA/CO).
    _d(61, MOTOR_CARRIER, "SixtyOne",   "any auto is covered",
       OWNED, HIRED, NONOWNED, SCHEDULED, PRIVATE_PASSENGER),
    _d(62, MOTOR_CARRIER, "SixtyTwo",   "owned autos only are covered",
       OWNED, SCHEDULED, PRIVATE_PASSENGER),
    _d(63, MOTOR_CARRIER, "SixtyThree", "owned private passenger autos only are covered",
       OWNED, PRIVATE_PASSENGER),
    _d(64, MOTOR_CARRIER, "SixtyFour",  "owned commercial autos only are covered",
       OWNED),
    _d(66, MOTOR_CARRIER, "SixtySix",   "owned autos subject to a compulsory uninsured motorist law are covered",
       OWNED),
    _d(67, MOTOR_CARRIER, "SixtySeven", "specifically described autos are covered",
       SCHEDULED),
    _d(68, MOTOR_CARRIER, "SixtyEight", "hired autos only are covered",
       HIRED),
    _d(69, MOTOR_CARRIER, "SixtyNine",  "trailers in your possession under a trailer interchange agreement are covered",
       TRAILER_INTERCHANGE),
    _d(70, MOTOR_CARRIER, "Seventy",    "your trailers in the possession of another trucker under a trailer interchange agreement are covered",
       TRAILER_INTERCHANGE),
    _d(71, MOTOR_CARRIER, "SeventyOne", "non-owned autos only are covered",
       NONOWNED),
]

# The four ACORD sets use disjoint number ranges, so a bare number identifies
# its family with no guessing. Asserted by the test suite.
BY_NUMBER: Dict[int, SymbolDef] = {s.number: s for s in _ALL}
BY_FAMILY: Dict[str, Dict[int, SymbolDef]] = {}
for _s in _ALL:
    BY_FAMILY.setdefault(_s.family, {})[_s.number] = _s

ALL_NUMBERS: FrozenSet[int] = frozenset(BY_NUMBER)

# The "any auto" symbol in each family. ACORD 25's `Vehicle_AnyAutoIndicator_A`
# and ACORD 131's `UnderlyingCoverage_Coverage_AnyAutoIndicator_A` (whose
# tooltip says "(symbol 1)" in as many words) are exactly this designation
# expressed as a checkbox.
ANY_AUTO_NUMBERS: FrozenSet[int] = frozenset(
    s.number for s in _ALL
    if {OWNED, HIRED, NONOWNED} <= s.covers
)


# ── Coverage labels ───────────────────────────────────────────────────────────
# Canonical coverage keys a symbol can be attached to. "unspecified" is what a
# document's covered-autos grid collapses to when the extraction could not tell
# which coverage line a number belonged to.

LIABILITY      = "liability"
COMPREHENSIVE  = "comprehensive"
COLLISION      = "collision"
PHYSICAL_DAMAGE = "physical_damage"
UM_UIM         = "um_uim"
MEDICAL        = "medical"
PIP            = "pip"
TOWING         = "towing"
DRIVE_OTHER_CAR = "drive_other_car"
UNSPECIFIED    = "unspecified"

COVERAGE_LABEL: Dict[str, str] = {
    LIABILITY:       "Liability",
    COMPREHENSIVE:   "Comprehensive",
    COLLISION:       "Collision",
    PHYSICAL_DAMAGE: "Physical Damage",
    UM_UIM:          "Uninsured/Underinsured Motorists",
    MEDICAL:         "Medical Payments",
    PIP:             "Personal Injury Protection",
    TOWING:          "Towing and Labor",
    DRIVE_OTHER_CAR: "Drive Other Car",
    UNSPECIFIED:     "Covered Autos",
}

# Ordered longest/most specific first - first hit wins.
_COVERAGE_PATTERNS = [
    (DRIVE_OTHER_CAR, ("drive other car", "driveothercar", "doc ")),
    (COMPREHENSIVE,   ("comprehensive", "other than collision", "otc", "comp")),
    (COLLISION,       ("collision", "coll")),
    (PHYSICAL_DAMAGE, ("physical damage", "physicaldamage", "phys dam", "phys. dam", "pd coverage")),
    (UM_UIM,          ("uninsured", "underinsured", "um/uim", "um / uim", "uim", "um")),
    (MEDICAL,         ("medical payments", "med pay", "medpay", "medical")),
    (PIP,             ("personal injury protection", "pip", "no-fault", "no fault")),
    (TOWING,          ("towing", "labor")),
    (LIABILITY,       ("liability", "bodily injury", "csl", "combined single limit", "bi/pd", "liab")),
]

# Coverages whose symbol answers "which autos does the LIABILITY part protect".
_LIABILITY_KEYS = (LIABILITY, UNSPECIFIED)
# Coverages that are physical damage.
PHYSICAL_DAMAGE_KEYS = (COMPREHENSIVE, COLLISION, PHYSICAL_DAMAGE)


def normalize_coverage(label) -> str:
    """Map any free-text coverage label onto a canonical coverage key."""
    if label is None:
        return UNSPECIFIED
    s = str(label).strip().lower()
    if not s:
        return UNSPECIFIED
    if s in COVERAGE_LABEL:
        return s
    for key, needles in _COVERAGE_PATTERNS:
        for n in needles:
            if n in s:
                return key
    return UNSPECIFIED


# ── Parsing ───────────────────────────────────────────────────────────────────

_NUM_RE = re.compile(r"\d{1,3}")
# A symbol reference in free text: "Symbol 7", "Sym. 07", or a bare number that
# sits next to a coverage label. Leading zeros are normal on dec pages ("01").
_LABELLED_RE = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z /&.\-]{2,40}?)\s*[:=\-]?\s*"
    r"(?:symbols?|sym\.?)?\s*"
    r"(?P<nums>\d{1,3}(?:\s*(?:,|/|and|&)\s*\d{1,3})*)",
    re.IGNORECASE,
)


def _clean_numbers(raw) -> List[int]:
    """Every integer in `raw`, de-duplicated, order preserved."""
    out: List[int] = []
    if raw is None:
        return out
    items: Iterable
    if isinstance(raw, (list, tuple, set)):
        items = raw
    else:
        items = [raw]
    for item in items:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            nums = [item]
        else:
            nums = [int(m) for m in _NUM_RE.findall(str(item))]
        for n in nums:
            if 0 < n < 200 and n not in out:
                out.append(n)
    return out


def parse_symbols(raw) -> Dict[str, List[int]]:
    """Normalize any stored shape of `auto_covered_symbols` into
    {coverage_key: [symbol numbers]}.

    Tolerant by design because this fact reaches us from four different places
    and all four must keep working:

      * current extraction  - [{"coverage": "liability", "symbols": [1]}, ...]
      * legacy extraction   - [1, 7]                    (pre-2026-08 sessions)
      * a producer answer   - "Liability 1, comp 7, collision 7"  (free text
                              typed into the issue-resolution modal)
      * a dict              - {"liability": [1], "comprehensive": [7]}
    """
    out: Dict[str, List[int]] = {}

    def _add(coverage: str, numbers: Iterable[int]) -> None:
        bucket = out.setdefault(coverage, [])
        for n in numbers:
            if n not in bucket:
                bucket.append(n)

    if raw is None:
        return out
    if isinstance(raw, dict) and "value" in raw and not any(
        k in raw for k in ("coverage", "symbols")
    ):
        raw = raw["value"]

    if isinstance(raw, dict):
        for k, v in raw.items():
            _add(normalize_coverage(k), _clean_numbers(v))
        return out

    if isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, dict):
                cov = normalize_coverage(
                    item.get("coverage") or item.get("cov") or item.get("line")
                )
                nums = _clean_numbers(
                    item.get("symbols") if item.get("symbols") is not None
                    else item.get("symbol")
                )
                _add(cov, nums)
            else:
                _add(UNSPECIFIED, _clean_numbers(item))
        return out

    text = str(raw).strip()
    if not text:
        return out
    matched = False
    for m in _LABELLED_RE.finditer(text):
        cov = normalize_coverage(m.group("label"))
        nums = _clean_numbers(m.group("nums"))
        if nums:
            matched = True
            _add(cov, nums)
    if not matched:
        _add(UNSPECIFIED, _clean_numbers(text))
    return out


def _fact_value(facts: dict, key: str):
    v = (facts or {}).get(key)
    if isinstance(v, dict) and "value" in v:
        v = v["value"]
    return v


def symbols_by_coverage(facts: dict) -> Dict[str, List[int]]:
    """Parsed `auto_covered_symbols` for this submission."""
    return parse_symbols(_fact_value(facts, "auto_covered_symbols"))


def all_numbers(facts: dict) -> List[int]:
    out: List[int] = []
    for nums in symbols_by_coverage(facts).values():
        for n in nums:
            if n not in out:
                out.append(n)
    return out


def symbols_for(facts: dict, *coverages: str) -> List[int]:
    """Symbol numbers designated for any of `coverages`.

    Falls back to the UNSPECIFIED bucket when the document showed a covered-autos
    grid but the extraction could not attribute a number to a specific coverage
    line - that is still real, quotable evidence, just less precise.
    """
    parsed = symbols_by_coverage(facts)
    out: List[int] = []
    for cov in coverages:
        for n in parsed.get(cov, []):
            if n not in out:
                out.append(n)
    if not out:
        for n in parsed.get(UNSPECIFIED, []):
            if n not in out:
                out.append(n)
    return out


def liability_symbols(facts: dict) -> List[int]:
    return symbols_for(facts, *_LIABILITY_KEYS)


# ── Reasoning ─────────────────────────────────────────────────────────────────

def detect_family(numbers: Iterable[int]) -> Optional[str]:
    """The ACORD symbol family these numbers belong to, or None if they are
    unrecognised or span more than one family."""
    fams = {BY_NUMBER[n].family for n in numbers if n in BY_NUMBER}
    return fams.pop() if len(fams) == 1 else None


def family_for(facts: dict, flags: Optional[dict] = None,
               triggered_ids: Optional[Iterable[str]] = None) -> str:
    """Which symbol family this submission is written on.

    The captured numbers decide it when they can (the four ACORD sets are
    disjoint). Only when nothing was captured do we fall back to the trucking
    flag and the selected forms.
    """
    fam = detect_family(all_numbers(facts))
    if fam:
        return fam
    ids = set(triggered_ids or ())
    if ids & {"ACORD_138_CA", "ACORD_138_CO", "ACORD_160"}:
        return GARAGE
    if (flags or {}).get("has_truckers_coverage"):
        return TRUCKERS
    return BUSINESS_AUTO


def unrecognised(numbers: Iterable[int]) -> List[int]:
    """Captured numbers this table does not define - ISO 5 / 19, or a
    company-unique symbol. Their presence means we must not draw conclusions."""
    return [n for n in numbers if n not in BY_NUMBER]


def covers(numbers: Iterable[int], exposure: str) -> Optional[bool]:
    """Does any of these symbols designate `exposure`?

    Returns None - "cannot say" - when nothing was captured or when an
    unrecognised symbol is present. Callers must treat None as "stay silent",
    never as False.
    """
    nums = list(numbers)
    if not nums:
        return None
    if unrecognised(nums):
        return None
    return any(exposure in BY_NUMBER[n].covers for n in nums)


def describe(number: int) -> str:
    """'1 (any auto is covered)' - for user-facing messages."""
    s = BY_NUMBER.get(number)
    return f"{number} ({s.description})" if s else str(number)


def describe_all(numbers: Iterable[int]) -> str:
    return ", ".join(describe(n) for n in numbers)


def indicator_field(number: int, row: str = "A") -> Optional[str]:
    """The ACORD checkbox field for this symbol, e.g.
    'Vehicle_BusinessAutoSymbol_OneIndicator_A'."""
    s = BY_NUMBER.get(number)
    if not s:
        return None
    return f"{FAMILY_FIELD_PREFIX[s.family]}{s.word}Indicator_{row}"


def indicator_fields_for(numbers: Iterable[int], row: str = "A") -> Dict[str, str]:
    """{acord_field: 'Yes'} for every recognised symbol in `numbers`."""
    out: Dict[str, str] = {}
    for n in numbers:
        f = indicator_field(n, row)
        if f:
            out[f] = "Yes"
    return out
