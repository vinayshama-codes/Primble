"""state_auto_grid.py - ACORD 137 (Commercial Auto Coverages / Limits, the CA
and CO state editions): which box holds which coverage, and what the package
says goes in it.

WHY THIS EXISTS (client Orbin audit 2026-09-11, item 10). Every auto fact the
137 needs was extracted - the $1M combined single limit, $5K medical payments,
$1M UM, the $1,000 deductibles and a covered-auto symbol per coverage - and the
generated form still forced the $1M blank and wiped the Med Pay / UM / comp /
collision symbols. Every resolver that touched it read it as an ACORD 127:

  * A 137 row LETTER names a COVERAGE row of a symbol grid, or a SECTION of the
    form (its page: Business Auto, Truckers, Motor Carrier) - never a vehicle.
    The phantom-vehicle rule blanked grid rows B-H as "vehicles 2-8" on a
    one-vehicle package, and the 127 deductible binding stamped the OWNED
    collision deductible into the Business Auto page's HIRED physical damage
    box - and, on any fleet of three, into the Truckers and Motor Carrier
    sections as well.
  * The 137 prints no separate CSL amount box. The CSL figure goes in the box
    printed "CSL / BI EA PER", chosen by the CSL tick beside it; the 127-shaped
    limit resolver treated that box as split-only, so a CSL policy's limit
    could never appear on this form.
  * Nothing bound Med Pay, UM or the comp deductible to a 137 box.

WHAT IS READ OFF THE TEMPLATE, AND WHAT IS A TABLE
  * Which PAGE (section) each field sits on is read at runtime from the
    template's own widgets, and the section is named by that page's own
    printed heading ("BUSINESS AUTO SECTION", ...). Cached per form.
  * Which COVERAGE each symbol-grid row is printed for, and which limit-basis
    tick sits on the liability row versus the UM row, are the two tables
    below. `tests/test_state_auto_grid_14sep.py` re-derives both from the
    printed row labels of every 137 template and fails the build on drift.

THE CONTRACT - the same one every owning resolver in pdf_service keeps
  SKIP      not decided here; every other path runs exactly as before
  None      an owned blank - gap fill is never asked
  ASK       owned, but only the DOCUMENT can answer it (no extracted fact
            carries the value) - gap fill is asked
  a string  the value - always an extracted fact, or the tick for a symbol the
            document attributed to that coverage. Nothing here guesses. A box
            printed for one amount only takes a fact stating exactly one.

A page is decided only for a family the package has EVIDENCE about: the
captured symbols self-identify their family (the four ACORD sets are
disjoint), and the truckers / motor carrier flags speak when no symbol was
captured. With no evidence either way every field is SKIP - today's behaviour.
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from types import MappingProxyType
from typing import Any, FrozenSet, List, Mapping, Optional, Tuple

from services import auto_symbols as _sym

logger = logging.getLogger(__name__)

SKIP = object()
ASK = "UNMATCHED"             # pdf_service's own "send to gap fill" token

FORMS: FrozenSet[str] = frozenset({"ACORD_137_CA", "ACORD_137_CO"})

_FAMILIES: Tuple[str, ...] = (_sym.BUSINESS_AUTO, _sym.TRUCKERS, _sym.MOTOR_CARRIER)

# A page's printed heading -> the family that page is for. Most specific first:
# the Motor Carrier page also prints the word TRUCKERS in its hired-auto rows.
_PAGE_HEADINGS: Tuple[Tuple[str, str], ...] = (
    ("MOTOR CARRIER SECTION", _sym.MOTOR_CARRIER),
    ("TRUCKERS SECTION",      _sym.TRUCKERS),
    ("BUSINESS AUTO SECTION", _sym.BUSINESS_AUTO),
)

# Specified Causes of Loss - `auto_symbols`' own key since 15 Sep 2026, so a
# symbol the declarations attribute to it ticks its own row and never the
# Comprehensive and Collision rows (where it went as generic physical damage).
# Nothing attributed to it: the row stays an owned blank, as before.
SPECIFIED_CAUSES = _sym.SPECIFIED_CAUSES

# Symbol-grid row letter -> the coverage that row is printed for, per family.
# Rows I/J/K of the Truckers and Motor Carrier grids are trailer interchange,
# which no symbol coverage key names; they are left to the paths that run today.
ROW_COVERAGE: Mapping[str, Mapping[str, str]] = MappingProxyType({
    _sym.BUSINESS_AUTO: MappingProxyType({
        "A": _sym.LIABILITY, "B": _sym.MEDICAL, "C": _sym.UM_UIM,
        "E": _sym.TOWING, "F": _sym.COMPREHENSIVE, "G": SPECIFIED_CAUSES,
        "H": _sym.COLLISION}),
    _sym.TRUCKERS: MappingProxyType({
        "A": _sym.LIABILITY, "B": _sym.MEDICAL, "C": _sym.UM_UIM,
        "E": _sym.COMPREHENSIVE, "F": SPECIFIED_CAUSES, "G": _sym.COLLISION,
        "H": _sym.TOWING}),
    _sym.MOTOR_CARRIER: MappingProxyType({
        "A": _sym.LIABILITY, "B": _sym.MEDICAL, "C": _sym.UM_UIM,
        "E": _sym.COMPREHENSIVE, "F": SPECIFIED_CAUSES, "G": _sym.COLLISION,
        "H": _sym.TOWING}),
})

# The CSL / BI-EACH-PERSON tick pairs: letter -> the coverage row it sits on.
# A/B on the Business Auto page, D/E on Truckers, G/H on Motor Carrier - the
# page itself says which family.
LIMIT_BASIS_ROW: Mapping[str, str] = MappingProxyType({
    "A": _sym.LIABILITY, "B": _sym.UM_UIM,
    "D": _sym.LIABILITY, "E": _sym.UM_UIM,
    "G": _sym.LIABILITY, "H": _sym.UM_UIM,
})

_GRID_FAMILY = {"BusinessAuto": _sym.BUSINESS_AUTO, "Truckers": _sym.TRUCKERS,
                "MotorCarrier": _sym.MOTOR_CARRIER}

_GRID_RE = re.compile(
    r"^Vehicle_(?P<grid>BusinessAuto|Truckers|MotorCarrier)Symbol_"
    r"(?P<word>[A-Za-z]+?)(?P<kind>Indicator|Code)_(?P<row>[A-Z]{1,2})$")
_BASIS_RE = re.compile(
    r"^Vehicle_(?P<which>CombinedSingleLimit_LimitIndicator"
    r"|BodilyInjury_EachPersonLimitIndicator)_(?P<row>[A-Z])$")
_CELL_RE = re.compile(r"^Vehicle_(?P<base>[A-Za-z]+_[A-Za-z]+)_(?P<row>[A-Z])$")

# The boxes printed under a physical damage COVERAGE / DEDUCTIBLE heading. On
# the Business Auto page they sit in the HIRED PHYSICAL DAMAGE block - the
# hired autos' deductible, which the owned autos' deductible is NOT evidence
# of (it depends on symbol 8 or an endorsement the facts do not carry). On the
# Truckers and Motor Carrier pages they are the owned autos' own physical
# damage deductibles. The page decides which, never the field name.
_PD_BASES = frozenset({
    "Comprehensive_DeductibleAmount", "Collision_DeductibleAmount",
    "SpecifiedCauseOfLoss_DeductibleAmount",
    "Coverage_ComprehensiveDeductibleIndicator", "Coverage_CollisionIndicator",
    "Coverage_SpecifiedCauseOfLossDeductibleIndicator",
    "Collision_DeductibleWaiverIndicator",
})
_OWNED_PD_DEDUCTIBLE_FACT = {
    "Comprehensive_DeductibleAmount": "auto_deductible_comp",
    "Collision_DeductibleAmount":     "auto_deductible_collision",
}
# What a HIRED or BORROWED auto costs, and how many days / vehicles its physical
# damage runs for, are rating inputs no extracted fact carries; a declarations
# page prints them, when at all, as a rate on an "IF ANY" basis. Asked of the
# document, the model read Orbin's "EXCESS CO IF ANY 100 $ 185.00" as a $100
# cost of hire, 100 days and 1 vehicle (live 15 Sep 2026). Owned blanks on
# every page - the producer states them. The Yes/No, state and "if any basis"
# boxes beside them are unchanged and still read the document.
_HIRED_EXPOSURE_BASES = frozenset({
    "HiredBorrowed_HiredCostAmount", "TruckersHiredBorrowed_HiredCostAmount",
    "HiredPhysicalDamage_DayCount", "HiredPhysicalDamage_VehicleCount",
})
# The hired / borrowed and non-owned LIABILITY Yes/No boxes. Which autos the
# liability part protects is exactly what a covered-auto symbol designates, so a
# symbol that PROVES the coverage decides the box: Symbol 1 is any auto, hired
# and non-owned included. Live 15 Sep 2026 (Orbin, run 5): the only "non-owned"
# line in 271 pages is the Symbol 9 DEFINITION, which the evidence gate rightly
# refuses as proof, so the box went blank beside a printed CO state on a Symbol 1
# policy. Only a proven YES is decided here: symbols that do not cover the
# exposure may be symbols extraction missed (an endorsement's Symbol 8), so that
# answer stays with the document, exactly as before.
_LIABILITY_EXPOSURE_RE = re.compile(
    r"^Vehicle_(?P<which>HiredBorrowed|TruckersHiredBorrowed|NonOwned)"
    r"_(?P<yn>Yes|No)Indicator_(?P<row>[A-Z])$")
_LIABILITY_EXPOSURE = {
    "HiredBorrowed":         _sym.HIRED,
    "TruckersHiredBorrowed": _sym.HIRED,
    "NonOwned":              _sym.NONOWNED,
}
_LIABILITY_PART = {
    "BodilyInjury_PerPersonLimitAmount":     0,   # printed "CSL / BI EA PER"
    "BodilyInjury_PerAccidentLimitAmount":   1,
    "PropertyDamage_PerAccidentLimitAmount": 2,
}
_UM_PART = {
    "UninsuredMotorists_BodilyInjuryPerPersonLimitAmount":   0,
    "UninsuredMotorists_BodilyInjuryPerAccidentLimitAmount": 1,
    "UninsuredMotorists_PropertyDamagePerAccidentLimit":     2,
}
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
# One part of a split limit: an amount and nothing else ("$25,000", "25", "25K").
# A part carrying words ("$1,000,000 CSL", "$5,000 deductible") is not a split
# part, so "$1M CSL / $5K deductible" can never be read as per person / per
# accident.
_SPLIT_PART_RE = re.compile(r"\$?\s*\d[\d,]*(?:\.\d+)?\s*[kKmM]?")


# ── Reading the template ─────────────────────────────────────────────────────

@lru_cache(maxsize=8)
def field_families(form_id: str) -> Mapping[str, str]:
    """{field name: the family of the page it is printed on}, read off the
    template's own widgets. Empty when the template cannot be read - every
    field is then SKIP, i.e. today's behaviour."""
    try:
        from config.settings import TEMPLATE_DIR
    except Exception:                                          # noqa: BLE001
        return MappingProxyType({})
    path = os.path.join(TEMPLATE_DIR, f"{form_id}.pdf")
    if not os.path.exists(path):
        return MappingProxyType({})
    out: dict = {}
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                heading = (page.extract_text() or "").upper()
                family = next((fam for words, fam in _PAGE_HEADINGS if words in heading), None)
                if family is None:
                    continue
                for annot in page.annots or []:
                    name = annot.get("title") or ""
                    if isinstance(name, bytes):
                        name = name.decode("latin-1", "ignore")
                    name = str(name).strip()
                    if name:
                        out.setdefault(name, family)
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("state_auto_grid: cannot read the %s template: %s", form_id, exc)
        return MappingProxyType({})
    return MappingProxyType(out)


# ── Reading the facts ────────────────────────────────────────────────────────

def _val(facts: Any, key: str) -> Any:
    v = facts.get(key) if isinstance(facts, dict) else None
    if isinstance(v, dict) and "value" in v:
        v = v.get("value")
    return v


def _amount(facts: Any, key: str) -> Optional[str]:
    """The fact's text when it states an amount (has a digit), else None."""
    v = _val(facts, key)
    if v is None or isinstance(v, (bool, list, dict)):
        return None
    text = str(v).strip()
    return text if re.search(r"\d", text) else None


def _one_amount(text: Optional[str]):
    """`text` when it states exactly ONE amount, ASK when it states several,
    None when there is nothing.

    A box printed for one amount never takes a fact carrying two: the display
    formatter keeps only the digits, so "$250,000/$500,000" would print as one
    number nobody wrote (14 Sep screen-level fuzz). Only the document can say
    which figure the box means.
    """
    if not text:
        return None
    return text if len(_NUMBER_RE.findall(text)) == 1 else ASK


def _flag(facts: Any, key: str) -> Optional[bool]:
    v = _val(facts, key)
    if isinstance(v, bool):
        return v
    text = str(v).strip().lower() if v is not None else ""
    if text in ("true", "yes", "1"):
        return True
    if text in ("false", "no", "0"):
        return False
    return None


def families(facts: Any) -> Tuple[FrozenSet[str], FrozenSet[str]]:
    """(present, absent): the 137 sections the package has evidence FOR and
    AGAINST. A family in neither set is unknown and its page is not decided.

    Captured symbols decide when there are any. With none, only the truckers /
    motor carrier flags speak - an explicit False is evidence of absence, a
    missing flag is not - and a plain auto flag makes Business Auto present.
    """
    numbers = _sym.all_numbers(facts)
    captured = {_sym.BY_NUMBER[n].family for n in numbers if n in _sym.BY_NUMBER}
    flag_says = {_sym.TRUCKERS: _flag(facts, "has_truckers_coverage"),
                 _sym.MOTOR_CARRIER: _flag(facts, "has_motor_carrier_coverage")}
    present = set(captured) | {fam for fam, said in flag_says.items() if said is True}
    if captured:
        absent = set(_FAMILIES) - present
    else:
        absent = {fam for fam, said in flag_says.items() if said is False}
        if (any(_flag(facts, k) is True for k in
                ("has_auto_coverage", "has_commercial_auto", "has_auto_liability"))
                and not present & {_sym.TRUCKERS, _sym.MOTOR_CARRIER}):
            present.add(_sym.BUSINESS_AUTO)
    present &= set(_FAMILIES)
    return frozenset(present), frozenset(absent - present)


def _designated(facts: Any, coverage: str) -> List[int]:
    """The symbol numbers the document attributed to `coverage`.

    Liability keeps `auto_symbols.liability_symbols` (which falls back to an
    unattributed grid - today's row-A behaviour). Every other row reads ONLY
    numbers attributed to its own coverage: an unattributed "1, 7" must never
    tick a Medical Payments or UM row.
    """
    if coverage == _sym.LIABILITY:
        return list(_sym.liability_symbols(facts))
    parsed = _sym.symbols_by_coverage(facts)
    out = list(parsed.get(coverage, []))
    if coverage in (_sym.COMPREHENSIVE, _sym.COLLISION):
        out += [n for n in parsed.get(_sym.PHYSICAL_DAMAGE, []) if n not in out]
    return out


def _read_limit(raw: str) -> Tuple[str, List[str]]:
    """How one limit fact is printed.

    ("csl", [raw])       exactly one amount ("$1,000,000 combined single limit")
    ("split", parts)     two or three "/"-separated parts, each a bare amount
    ("ambiguous", [])    anything else - the document decides, never a guess
    """
    parts = [p.strip() for p in raw.split("/")]
    if len(parts) in (2, 3) and all(_SPLIT_PART_RE.fullmatch(p) for p in parts):
        return "split", parts
    if len(_NUMBER_RE.findall(raw)) == 1:
        return "csl", [raw]
    return "ambiguous", []


def liability_limits(facts: Any) -> Tuple[Optional[str], List[Optional[str]]]:
    """The auto liability limit as the 137 prints it.

    ("split", [per person, per accident, pd]) - the `auto_split_limits` flag,
        else `coverage_evidence.auto_split_limits_stated` (the reading
        pdf_service's own auto-limit resolver uses), else a CSL fact that is
        itself written as a split;
    ("csl", [limit]); ("ambiguous", []); (None, []) when nothing is stated.
    """
    split = _flag(facts, "auto_split_limits") is True
    if not split:
        try:
            from services.coverage_evidence import auto_split_limits_stated
            split = bool(auto_split_limits_stated(facts))
        except Exception:                                      # noqa: BLE001
            split = False
    if split:
        return "split", [_amount(facts, k) for k in
                         ("auto_bi_per_person", "auto_bi_per_accident", "auto_pd_per_accident")]
    raw = _amount(facts, "auto_liability_limit")
    if not raw:
        return None, []
    shape, parts = _read_limit(raw)
    if shape == "split":
        return "split", (list(parts) + [None, None, None])[:3]
    return shape, parts


def um_limits(facts: Any) -> Tuple[Optional[str], List[str]]:
    """How `auto_um_uim_limit` is printed - `_read_limit`'s three shapes, or
    (None, []) when no amount is stated."""
    raw = _amount(facts, "auto_um_uim_limit")
    if not raw:
        return None, []
    return _read_limit(raw)


def _unstated(facts: Any, coverage: str):
    """A coverage whose value no fact carries: ask the document when the
    package attributes a symbol to it, own a blank when the symbol table was
    read and it is not there, and change nothing when no symbol was read."""
    if _designated(facts, coverage):
        return ASK
    return None if _sym.all_numbers(facts) else SKIP


# ── The three kinds of box ───────────────────────────────────────────────────

def _grid_cell(family: str, word: str, kind: str, row: str, facts: Any,
               universe: Mapping[str, str]):
    coverage = ROW_COVERAGE[family].get(row)
    if coverage is None:
        return SKIP
    designated = _designated(facts, coverage)
    if not designated:
        # Liability keeps today's behaviour (the model reads the dec's own
        # liability line). Every other row cannot be identified by a reader of
        # the tooltips - they are word-for-word identical row to row - so an
        # unattributed row is an owned blank, never a guess.
        return SKIP if coverage == _sym.LIABILITY else None
    table = _sym.BY_FAMILY.get(family, {})
    own = [n for n in designated if n in table]
    unknown = [n for n in designated if n not in _sym.BY_NUMBER]
    if not own and not unknown:
        return None                     # every symbol belongs to another family
    prefix = _sym.FAMILY_FIELD_PREFIX[family]
    printed = {n for n, s in table.items() if f"{prefix}{s.word}Indicator_{row}" in universe}
    unprinted = [n for n in own if n not in printed] + unknown
    if word == "OtherSymbol":
        if kind == "Indicator":
            return "Yes" if unprinted else "No"
        return ", ".join(str(n) for n in unprinted) if unprinted else None
    if kind != "Indicator":
        return SKIP
    sdef = next((s for s in table.values() if s.word == word), None)
    if sdef is None:
        return SKIP
    return "Yes" if sdef.number in own else "No"


def _basis_cell(which: str, row: str, facts: Any):
    coverage = LIMIT_BASIS_ROW.get(row)
    if coverage is None:
        return SKIP
    if coverage == _sym.LIABILITY:
        structure, _parts = liability_limits(facts)
        if structure is None:
            return SKIP
    else:
        structure, _parts = um_limits(facts)
        if structure is None:
            return _unstated(facts, _sym.UM_UIM)
    if structure == "ambiguous":
        return ASK
    is_csl_box = which.startswith("CombinedSingleLimit")
    return "Yes" if (structure == "csl") == is_csl_box else "No"


def _liability_exposure_cell(family: str, which: str, yn: str, facts: Any):
    """A hired / non-owned liability YES-NO box, from the liability symbols of
    THIS page's family. Decided only when they prove the exposure is covered;
    SKIP (the document decides) otherwise."""
    liability = _designated(facts, _sym.LIABILITY)
    if not liability or _sym.unrecognised(liability):
        return SKIP                 # nothing captured, or a symbol we cannot read
    own = [n for n in liability if _sym.BY_NUMBER[n].family == family]
    if _sym.covers(own, _LIABILITY_EXPOSURE[which]) is not True:
        return SKIP
    return "Yes" if yn == "Yes" else "No"


def _cell(family: str, base: str, facts: Any):
    if base in _LIABILITY_PART:
        structure, parts = liability_limits(facts)
        if structure is None:
            return SKIP
        if structure == "ambiguous":
            return ASK
        idx = _LIABILITY_PART[base]
        if structure == "csl":
            # The "CSL / BI EA PER" box holds the combined single limit; a CSL
            # has no per-accident or property-damage figure to state.
            return parts[0] if idx == 0 else None
        return _one_amount(parts[idx]) if idx < len(parts) else None
    if base == "MedicalPayments_PerPersonLimitAmount":
        return _one_amount(_amount(facts, "auto_med_pay_limit")) or _unstated(facts, _sym.MEDICAL)
    if base in _UM_PART:
        structure, parts = um_limits(facts)
        if structure == "ambiguous":
            return ASK
        if structure is None:
            return _unstated(facts, _sym.UM_UIM)
        idx = _UM_PART[base]
        if structure == "csl":
            return parts[0] if idx == 0 else None
        return _one_amount(parts[idx]) if idx < len(parts) else None
    if base == "TowingAndLabour_LimitAmount":
        return _unstated(facts, _sym.TOWING)
    if base in _PD_BASES:
        if family == _sym.BUSINESS_AUTO:
            return ASK                  # HIRED physical damage - see _PD_BASES
        fact = _OWNED_PD_DEDUCTIBLE_FACT.get(base)
        return (_one_amount(_amount(facts, fact)) if fact else None) or ASK
    return SKIP


# ── The door ─────────────────────────────────────────────────────────────────

def resolve(form_id: str, field_name: str, facts: Any):
    """SKIP / None / ASK / a value for one ACORD 137 field - see the module
    docstring. Never raises on bad input; callers still wrap it."""
    if form_id not in FORMS:
        return SKIP
    name = str(field_name or "")
    if not name.startswith("Vehicle_"):
        return SKIP
    universe = field_families(form_id)
    page = universe.get(name)
    if page is None:
        return SKIP
    present, absent = families(facts)
    if page in absent:
        return None                     # a section the package does not carry
    if page not in present:
        return SKIP
    m = _GRID_RE.match(name)
    if m:
        if _GRID_FAMILY[m.group("grid")] != page:
            return SKIP
        return _grid_cell(page, m.group("word"), m.group("kind"), m.group("row"),
                          facts, universe)
    m = _LIABILITY_EXPOSURE_RE.match(name)
    if m:                               # symbols self-identify: `shared` is moot
        return _liability_exposure_cell(page, m.group("which"), m.group("yn"), facts)
    # Symbols self-identify their family; limits and deductibles do not. A
    # package written on two families gives no way to tell which section an
    # `auto_*` figure belongs to, so the document decides.
    shared = len(present) > 1
    m = _BASIS_RE.match(name)
    if m:
        out = _basis_cell(m.group("which"), m.group("row"), facts)
        return ASK if (shared and out is not SKIP) else out
    m = _CELL_RE.match(name)
    if m:
        if m.group("base") in _HIRED_EXPOSURE_BASES:
            return None                 # no fact states it, on any page
        out = _cell(page, m.group("base"), facts)
        return ASK if (shared and out is not SKIP) else out
    return SKIP
