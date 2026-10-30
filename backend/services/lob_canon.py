"""lob_canon.py - which standard line of business a printed phrase names.

LEAF MODULE. Imports nothing from the rest of the service layer, so every
consumer (extraction, stamping, scoring, conflict detection) imports it
directly - no lazy import, no ``except: lambda _s: None`` fallback that used
to turn a circular-import blip into silently-disabled canonicalisation
(V1 plan C1-B, defect B6).

THE RULE (client V1 1.7, verbatim): *"If terminology is not covered by a known
normalization rule, do not automatically assume equivalence. Leave it
unmapped."* So this module maps from EXPLICIT allow-lists only, in a fixed
order, and returns None for anything it does not recognise. None is a real
answer - "cannot place" - and callers blank rather than guess.

Two mistakes this replaces, both measured (C1-B FLAG 4):

  * The previous generic fallback mapped ANY phrase containing the bare word
    "liability" to General Liability once nothing specific matched. So
    Professional Liability, Employment Practices Liability, Pollution
    Liability and D&O all became "General Liability" - the mirror image of the
    client's complaint (calling different things equal instead of equal things
    different). A COI listing Professional Liability then "agreed" with a GL
    dec page, and ACORD 126 could take a Professional Liability policy number.
  * ``Computer Coverage`` - named by the client as an Inland Marine component -
    returned None.

Known SPECIALTY liability lines now get their OWN family (``professional``,
``epli``, ``pollution``, ``directors_officers``, ``employee_benefits``,
``liquor``). That is not a new equivalence - it is a DISTINCTION: the only
thing any consumer does with a family is test ``== "general_liab"`` /
``== "auto"`` / ``in covered_canons``, so a distinct token simply stops the
specialty line from masquerading as GL. Adding a family here still requires
product approval (V1 decision D9); folding a phrase into an EXISTING family
requires the same.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Canonical family tokens. Strings, not an Enum, because every existing
# consumer compares against these literals and they are persisted nowhere.
GENERAL_LIAB = "general_liab"
AUTO = "auto"
UMBRELLA = "umbrella"
WORKERS_COMP = "workers_comp"
PROPERTY = "property"
INLAND_MARINE = "inland_marine"
CRIME = "crime"
CYBER = "cyber"
PROFESSIONAL = "professional"
EPLI = "epli"
POLLUTION = "pollution"
DIRECTORS_OFFICERS = "directors_officers"
EMPLOYEE_BENEFITS = "employee_benefits"
LIQUOR = "liquor"

# SPECIFIC coverage names, tried FIRST and in this order. "Employers
# Liability" is Workers Comp and must be tested before anything that could
# claim the word "liability"; "Commercial Liability Umbrella" is an umbrella
# before it is anything else. The order is pinned by tests.
_SPECIFIC: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (WORKERS_COMP,  ("workers compensation", "workers comp", "workmans compensation",
                     "employers liability", "work comp")),
    (UMBRELLA,      ("umbrella", "excess")),
    (INLAND_MARINE, ("inland marine", "installation", "contractors equipment",
                     "equipment floater", "computer coverage", "computer equipment",
                     "electronic data processing", "edp coverage",
                     "motor truck cargo", "bailee")),
    (AUTO,          ("auto", "automobile", "vehicle", "trucker", "motor carrier",
                     "garage")),
    (CYBER,         ("cyber", "network security", "privacy liability", "data breach")),
    (PROPERTY,      ("property", "building", "business personal property", "bpp")),
    # "dishonesty" widened from "employee dishonesty" 2026-09-03: the ISO 3-D
    # policy prints as "Comprehensive Dishonesty, Disappearance and
    # Destruction", which matched nothing - and once `canon_part` can read a
    # bare "Comprehensive" as Auto physical damage, a phrase this table cannot
    # place is no longer harmless. No other line of business uses the word.
    (CRIME,         ("crime", "fidelity", "dishonesty", "employee theft")),
)

# A phrase that CONTAINS a family's own word while naming something else.
# Masked out of the string before that family is tested, and ONLY that family -
# the same word may be perfectly good evidence elsewhere.
#
# Measured defect (client SYS-05 sweep, 2026-09-03): "Property Damage Liability"
# returned PROPERTY. "Property damage" is a category of LOSS that a LIABILITY
# policy pays for - it is the standard second half of every GL and Auto
# liability limit ("Bodily Injury and Property Damage Liability") - and it is
# not the Commercial Property line. So a COI's GL limit row could be read as a
# Property line, and `denied_families` / the cross-document LOB compare would
# then reason about a Property line the package does not carry.
#
# THE WORD IS NOT REMOVED FROM THE STRING, only from PROPERTY's own haystack:
# "Business Personal Property" still resolves, and after masking
# "Property Damage Liability" falls through to the bare-"liability" branch,
# whose tokens are all GL vocabulary, and lands on GENERAL_LIAB where it belongs.
_FAMILY_BLIND_PHRASES: dict = {
    # "property protection insurance" is Michigan's no-fault AUTO coverage
    # (8 Oct 2026: the Choice Electric auto dec's "Property Protection Insurance
    # (Michigan Only)" row made the auto policy a source of the Property line).
    PROPERTY: ("property damage", "property protection"),
}

# Z38: the same idea for a phrase that is a PREFIX of another word. "work
# comp" (an abbreviation) matched inside "WORK - Completed Ops" ("work
# completed ops") and read the completed-work part as Workers Compensation.
# Local to `canon_line` on purpose - not in the flattened export below.
_FAMILY_BLIND_PATTERNS: dict = {
    WORKERS_COMP: (re.compile(r"\bwork comp(?=[a-z])(?!ensation)"),),
}

# The same phrases, flattened, for consumers that tokenise a line name WITHOUT
# knowing which family they are about to compare it against.
#
# Exported because `pdf_service` holds a THIRD line-of-business matcher
# (`_lob_tokens` / `_lob_indicator_index`, which compares a document's words to
# ACORD's own checkbox tooltips) and it had the identical hole: the Commercial
# Property checkbox's token set is literally {"property"}, so
# "Bodily Injury And Property Damage Liability" matched it. Measured on the
# SYS-05 live run - the GL policy number then appeared to span General Liability
# AND Commercial Property, `_line_list_is_trustworthy` declared the list corrupt,
# and the package's total premium could not be computed at all.
#
# One definition, three readers. Fixing `canon_line` alone left the defect the
# client reported alive in a different matcher.
NON_LINE_PHRASES: Tuple[str, ...] = tuple(
    p for phrases in _FAMILY_BLIND_PHRASES.values() for p in phrases
)


def strip_non_line_phrases(text: Any) -> str:
    """`text` with every phrase that merely CONTAINS a line's word removed.

    For tokenisers. Returns the text otherwise untouched, so a caller that
    splits on non-letters behaves exactly as before on every other input.
    """
    s = str(text or "")
    lowered = s.lower()
    for phrase in NON_LINE_PHRASES:
        if phrase in lowered:
            # Rebuild case-insensitively without a regex: the phrases are plain
            # words, and a caller may pass any casing.
            out, i = [], 0
            while True:
                j = lowered.find(phrase, i)
                if j < 0:
                    out.append(s[i:])
                    break
                out.append(s[i:j])
                out.append(" ")
                i = j + len(phrase)
            s = "".join(out)
            lowered = s.lower()
    return s

# KNOWN specialty liability lines. Each is its own family so it can never be
# read as General Liability. Tried AFTER the specific table and BEFORE the GL
# allow-list so "Employee Benefits Liability" cannot fall into GL by carrying
# the word "liability".
_SPECIALTY: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (PROFESSIONAL,       ("professional", "errors and omissions", "errors omissions",
                          "e and o", "e o liability", "malpractice")),
    (EPLI,               ("employment practices", "epli", "epl ")),
    (POLLUTION,          ("pollution", "environmental")),
    (DIRECTORS_OFFICERS, ("directors and officers", "directors officers",
                          "d and o", "management liability")),
    # The singular is how ISO's own coverage part prints ("EMPLOYEE BENEFIT
    # LIABILITY COVERAGE PART", Choice Electric 6 Oct 2026) - it reached the
    # producer as "Coverage part not recognised". Only the LIABILITY phrase:
    # an "employee benefit plan" is a crime / ERISA fidelity subject, not EBL.
    (EMPLOYEE_BENEFITS,  ("employee benefits", "employee benefit liability",
                          "employee benefit liab")),
    (LIQUOR,             ("liquor",)),
)

# BARE ABBREVIATIONS - OWNER RULING 2026-08-28, the product approval D9 requires.
#
# Client beta-exit criterion: *"Equivalent coverage terminology does not create
# false warnings."* `GL`, `WC` and `BAP` are the three abbreviations a broker
# actually types, and all three returned None - so the most common shorthand in
# the business was "terminology not covered by a known rule". Logged as O2 in
# the C4 backlog since 2026-08-26 and left for a ruling because D9 reserves
# "folding a phrase into an existing family" for product. The owner ruled on
# 2026-08-28: add them. NOTHING BEYOND THESE THREE - a fourth abbreviation is a
# fresh D9 decision, not an obvious extension of this one.
#
# These are NOT in the tables above, and that is the whole point.
# `_SPECIFIC` / `_GL_PHRASES` match by SUBSTRING (`p in s`), which is safe for a
# multi-word phrase and catastrophic for a two-letter one. Measured before
# writing this:
#
#     "burglary and theft" contains "gl"   -> a CRIME line read as GL
#     "plate glass"        contains "gl"   -> a PROPERTY line read as GL
#     "roofing shingles"   contains "gl"   -> a roofer's own trade read as GL
#     "showcase"/"newcastle" contain "wc"  -> read as Workers Comp
#
# So abbreviations match WHOLE TOKENS only, using the same `s.split()` test the
# bare-"liability" branch below already uses. This is the D9 risk in miniature:
# the danger was never the equivalence, it was the matching mechanism.
_ABBREVIATIONS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (GENERAL_LIAB,  ("gl",)),
    (WORKERS_COMP,  ("wc",)),
    (AUTO,          ("bap",)),          # Business Auto Policy
)

# ACORD AL3 line-of-business CODES (Z37 lane B, owner-approved 24 Oct 2026 -
# the D9 / D57 decision for this set). An agency system prints them beside or
# instead of the line name ("UMBRC", "INMRC", "WORK"). Matched as WHOLE tokens,
# never substrings, and checked AFTER `_SPECIFIC` like `_ABBREVIATIONS`.
# None = recognised but not a line family: CPKGE is a package CONTAINER
# (`is_container_label`), BOP a Business Owners policy, which has no family
# here (its long name "Businessowners" maps to none either - a new family is
# a D9 decision of its own). "WORK" is an English word, so it counts only when
# it is the whole label ("WORK", "WORK (Expiring)"), never "Completed Work".
ACORD_LOB_CODES: Dict[str, Optional[str]] = {
    "cgl": GENERAL_LIAB,
    "autob": AUTO,
    "garag": AUTO,
    "umbrc": UMBRELLA,
    "exlia": UMBRELLA,          # excess liability: umbrella family, excess layer
    "inmrc": INLAND_MARINE,
    "propc": PROPERTY,
    "work": WORKERS_COMP,
    "cpkge": None,
    "bop": None,
}
_LOB_CODE_WORDS = frozenset({"work"})
# Z38: "WORK - Completed Ops" is the completed-WORK coverage part, not the WC
# code. A dash remainder naming a coverage part or another line rules the
# code out; a carrier / status remainder ("WORK - Magnolia", "WORK - Expiring")
# does not.
_CODE_REMAINDER_PART_WORDS = frozenset({
    "ops", "operations", "products", "product", "completed", "premises"})


def _code_remainder_names_other_coverage(text: Any, family: Optional[str]) -> bool:
    s = re.sub(r"\([^)]*\)", " ", str(text or ""))
    parts = re.split(r"\s[-–—]\s", s, maxsplit=1)
    if len(parts) < 2:
        return False
    rest = parts[1]
    if set(_clean(rest).split()) & _CODE_REMAINDER_PART_WORDS:
        return True
    try:
        other = canon_line(rest)
    except Exception:                                          # noqa: BLE001
        other = None
    return bool(other and other != family)


def acord_lob_code_family(text: Any) -> Optional[str]:
    """The family an ACORD LOB code in `text` names, or None."""
    words = [w for w in _container_text(text).split() if w not in _CONTAINER_FILLER]
    if len(words) == 1 and words[0] in _LOB_CODE_WORDS:
        fam = ACORD_LOB_CODES[words[0]]
        if _code_remainder_names_other_coverage(text, fam):
            return None
        return fam
    for w in _clean(text).split():
        if w in ACORD_LOB_CODES and w not in _LOB_CODE_WORDS and ACORD_LOB_CODES[w]:
            return ACORD_LOB_CODES[w]
    return None


# Phrases that name General Liability outright.
_GL_PHRASES: Tuple[str, ...] = (
    "general liability", "cgl", "premises operations", "premises liability",
    "products completed operations", "products liability",
    "completed operations",
)

# When the phrase contains the bare word "liability" and nothing above
# matched, it is General Liability ONLY if every word in it is generic GL
# vocabulary. "Commercial Liability" -> GL. "Liability" -> GL (Q6, current
# behaviour kept). "Widget Liability" -> None: an unknown qualifier is exactly
# the "terminology not covered by a known rule" the client says must not be
# assumed equivalent to anything.
GL_GENERIC_TOKENS = frozenset({
    "commercial", "general", "liability", "liab", "coverage", "policy",
    "insurance", "line", "cgl", "section", "part", "form", "occurrence",
    "claims", "made", "bodily", "injury", "property", "damage", "the", "and",
    "of", "coverages",
})


# ── COVERAGE PARTS - a component INSIDE a line, not a line of its own ───────
#
# Client SYS-05 (P0, 2026-09-01 live test): *"Terms such as UNINSURED AND
# UNDERINSURED MOTORISTS, COMPREHENSIVE, COLLISION, and Uninsured Motorists are
# being treated as unrecognized coverage parts. They are components of
# Automobile coverage and should not become standalone unknown lines. Map these
# terms into the Commercial Auto/Automobile coverage family BEFORE
# cross-document comparison."*
#
# ROOT CAUSE, and it is not an Auto problem. A declarations page prints a
# SCHEDULE OF COVERAGES whose rows are the coverage PARTS of one line, each
# with its own limit and premium, and RULE 16 asks the model for "one entry per
# coverage line ... as the document prints it". So extraction correctly emits
# them and `coverage_lines` has exactly one bucket for two different concepts:
#
#     Business Auto   $2,991   <- a LINE of business
#     Comprehensive   $412     <- a PART of that line
#     Collision       $688     <- a PART of that line
#     Uninsured Motorists      <- a PART of that line
#
# The same hole was measured on every other line, not just Auto: "Personal and
# Advertising Injury" and "Damage to Premises Rented to You" (GL parts),
# "Business Income", "Ordinance or Law", "Equipment Breakdown" (Property
# parts) all returned None too. Fixing only the four words in the client's
# screenshot would be the pinpoint patch, so the whole class is mapped here.
#
# THIS IS A SEPARATE DOOR FROM `canon_line` ON PURPOSE. `canon_line` answers
# "does this phrase NAME a line?" and its answer is what decides whether a row
# GRANTS or DENIES coverage (`denied_families`, `coverage_evidence`,
# `_coverage_lines_are_self_contradictory`). A part is not a line, so it must
# not become independent proof that a line exists - a lone "COLLISION - NO
# COVERAGE" row must never deny the whole Auto line, and a Collision row must
# not on its own flip an HNOA-only account into an owned-fleet one. Parts are
# for PLACEMENT (which line does this belong to) and COMPARISON only.

# Parts whose phrase can belong to exactly ONE line, whatever else is in the
# package. "motorist" is the whole UM/UIM family in every printing the phrase
# takes ("Uninsured Motorists", "UNINSURED AND UNDERINSURED MOTORISTS",
# "UM/UIM Motorist Coverage") and there is no non-auto motorist coverage.
_PART_UNAMBIGUOUS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    # "drive other car" (CA 99 10, Broadened Coverage For Named Individuals),
    # 15 Sep 2026: the Orbin auto dec prints it as a premium row on the auto
    # policy and it reached the producer as unrecognised terminology. It is a
    # Business Auto endorsement and nothing else - the same SYS-05 class.
    (AUTO,         ("motorist", "um uim", "uninsured", "underinsured",
                    "collision", "towing", "rental reimbursement",
                    "personal injury protection", "pip coverage",
                    "loss of use", "hired car", "drive other car",
                    "broadened coverage for named individuals")),
    (GENERAL_LIAB, ("personal and advertising injury",
                    "personal advertising injury", "advertising injury",
                    "damage to premises rented", "premises rented to you",
                    "fire damage legal", "fire legal liability",
                    "medical expense")),
    (PROPERTY,     ("business income", "business interruption", "extra expense",
                    "ordinance or law", "equipment breakdown",
                    "boiler and machinery")),
    # Crime parts. Added 2026-09-03 when the SYS-05 live fixture printed
    # "Forgery Or Alteration" under a 3-D policy and it surfaced as unplaceable
    # terminology - the same defect class as the Auto rows the client reported,
    # one coverage line over. Each names a crime insuring agreement and nothing
    # else: "forgery", "computer fraud" and "funds transfer fraud" appear on no
    # other line. "alteration" alone is deliberately absent - a building
    # alteration is a property exposure, not a crime coverage.
    (CRIME,        ("forgery", "money and securities", "computer fraud",
                    "funds transfer fraud", "counterfeit")),
)

# Parts whose phrase is genuinely shared between lines. "COMPREHENSIVE" is Auto
# physical damage on an auto schedule, but "Comprehensive Crime" and
# "Comprehensive General Liability" (the pre-1986 name for CGL) are real; "Medical
# Payments" and "Bodily Injury" sit on both a GL and an Auto dec page.
#
# These resolve ONLY when the package already shows the parent line - the
# "structural second condition" pattern H1-F made a standing rule after a test
# that was necessary but not sufficient deleted 13 of 14 real schedules. The
# phrase alone is never enough. No parent in the package -> stays unplaced ->
# routes to the producer exactly as it does today (Principle 7).
#
# `canon_line` is consulted BEFORE this table, so "Comprehensive General
# Liability" and "Comprehensive Crime" resolve as LINES and never reach it.
# A phrase listed under TWO families here is ambiguous in a package that
# carries both, and `canon_part` then refuses rather than picking one - a
# coverage part attributed to the wrong line is a coverage misstatement, and
# Principle 4 says a genuine conflict routes to the producer instead of being
# silently resolved. "Bodily Injury" and "Property Damage" are the standard
# liability limit rows on BOTH a GL and an Auto dec page, so they resolve on a
# monoline package and stay unplaced on a package carrying both.
_PART_NEEDS_PARENT: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (AUTO,         ("comprehensive", "other than collision", "physical damage",
                    "medical payments", "med pay",
                    "bodily injury", "property damage")),
    (GENERAL_LIAB, ("bodily injury", "property damage",
                    "medical payments", "med pay")),
)


def _clean(text: Any) -> str:
    s = re.sub(r"[^a-z ]", " ", str(text or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def canon_line(text: Any) -> Optional[str]:
    """Cached `_canon_line` for a string (the tables are constants; the scorer and
    the review plan call it ~90,000 times per pre-form page, 28 Oct)."""
    if isinstance(text, str):
        return _canon_line_cached(text)
    return _canon_line(text)


@functools.lru_cache(maxsize=65536)
def _canon_line_cached(text: str) -> Optional[str]:
    return _canon_line(text)


def _canon_line(text: Any) -> Optional[str]:
    """Which standard line of business a free-text line name denotes, or None.

    Resolution order: specific coverage names -> known specialty liability
    lines -> explicit GL phrases -> bare "liability" made only of generic GL
    words. Anything else is None, deliberately: callers must be able to tell
    "not this line" from "cannot tell", and blank rather than guess.
    """
    s = _clean(text)
    if not s:
        return None
    padded = f" {s} "
    for key, phrases in _SPECIFIC:
        # A family never sees the phrases that merely CONTAIN its own word while
        # naming something else ("property damage" is not the Property line).
        hay = s
        for blind in _FAMILY_BLIND_PHRASES.get(key, ()):
            hay = hay.replace(blind, " ")
        for blind_re in _FAMILY_BLIND_PATTERNS.get(key, ()):
            hay = blind_re.sub(" ", hay)
        if any(p in hay for p in phrases):
            return key
    for key, phrases in _SPECIALTY:
        if any((p in s) if not p.endswith(" ") else (p in padded) for p in phrases):
            return key
    # Abbreviations are checked AFTER the specific table on purpose, so
    # "Excess GL" stays UMBRELLA exactly as "Excess General Liability" does.
    # Putting them first would let an excess policy masquerade as the primary
    # line it sits over - the C23 defect, which put a $3M umbrella limit in the
    # GL boxes. Deliberately never the other way round.
    _tokens = set(s.split())
    for key, abbreviations in _ABBREVIATIONS:
        if _tokens.intersection(abbreviations):
            return key
    _coded = acord_lob_code_family(text)
    if _coded:
        return _coded
    if any(p in s for p in _GL_PHRASES):
        return GENERAL_LIAB
    if "liability" in s.split() or "liab" in s.split():
        if set(s.split()) <= GL_GENERIC_TOKENS:
            return GENERAL_LIAB
        return None
    return None


def canon_part(text: Any, present_families: Any = (),
               policy_family: Any = None) -> Optional[str]:
    """Which line this phrase is a coverage PART of, or None.

    NOT a claim that the phrase names a line - see the block comment above
    `_PART_UNAMBIGUOUS`. Answers only "if this row belongs to something, what?".

    `present_families` is the set of families the SAME package already
    establishes by other means. It is required for the shared phrases and
    ignored for the unambiguous ones. Passing nothing is safe: the ambiguous
    table simply never fires, which is today's behaviour.

    `policy_family` is the family of the CONTRACT this row was printed under,
    when the document states one. It is the strongest evidence available and it
    settles a phrase two present lines would otherwise both claim - a MEDICAL
    PAYMENTS row carrying the auto policy's number is the auto policy's medical
    payments. It can only ever narrow the candidates this table already
    produced, so it can never invent a placement for a phrase that is not a
    known coverage part.
    """
    s = _clean(text)
    if not s:
        return None
    # A phrase that names a line outright is a LINE, not a part. Checked first
    # so "Comprehensive General Liability" and "Comprehensive Crime" can never
    # be dragged into Auto by the bare word "comprehensive".
    if canon_line(s):
        return None
    for key, phrases in _PART_UNAMBIGUOUS:
        if any(p in s for p in phrases):
            return key
    try:
        present = frozenset(present_families or ())
    except TypeError:                                        # pragma: no cover
        present = frozenset()
    candidates = {key for key, phrases in _PART_NEEDS_PARENT
                  if key in present and any(p in s for p in phrases)}
    if len(candidates) > 1 and policy_family in candidates:
        return policy_family
    # ONE candidate or none. Two present lines that both print this row, with
    # nothing structural to separate them, is a genuine ambiguity - and
    # guessing is the forbidden move (Principle 4).
    return next(iter(candidates)) if len(candidates) == 1 else None


def _policy_key(entry: Any) -> str:
    """Punctuation-blind policy number, or "" - the same shape the extraction
    layer's own pairing checks use, so one printing cannot look like two."""
    if not isinstance(entry, dict):
        return ""
    return re.sub(r"[^a-z0-9]", "", str(entry.get("policy_number") or "").lower())


def policy_number_families(coverage_lines: Any) -> dict:
    """{policy number: the ONE family its named lines resolve to}.

    Built from rows that NAME a line only, so a part can never define the
    contract it is then placed by. A number attached to two different families
    is dropped: `_coverage_lines_are_self_contradictory` already treats that
    pairing as corrupt, and a corrupt witness must not settle an ambiguity.
    """
    by_num: dict = {}
    if not isinstance(coverage_lines, list):
        return {}
    for entry in coverage_lines:
        key = _policy_key(entry)
        fam = canon_line(entry.get("line")) if isinstance(entry, dict) else None
        if key and fam:
            by_num.setdefault(key, set()).add(fam)
    return {k: next(iter(v)) for k, v in by_num.items() if len(v) == 1}


def coverage_families_present(coverage_lines: Any) -> frozenset:
    """Families this package establishes on its own evidence.

    Two passes, because a package can name a line ONLY through its parts. The
    client's own document is that case: it prints COMPREHENSIVE / COLLISION /
    UNINSURED MOTORISTS as sibling rows, and "Collision" is unambiguous proof
    of an Auto line, which is then what lets the bare "COMPREHENSIVE" beside it
    resolve. A lone "COMPREHENSIVE" on a crime package still resolves to
    nothing, which is the point.
    """
    if not isinstance(coverage_lines, list):
        return frozenset()
    names = [str(e.get("line") or "") for e in coverage_lines if isinstance(e, dict)]
    present: set = {c for n in names if (c := canon_line(n))}
    present |= {c for n in names if (c := canon_part(n))}
    return frozenset(present)


def canon_line_or_part(text: Any, present_families: Any = ()) -> Optional[str]:
    """The line this phrase belongs to, whether it NAMES one or is a PART of one.

    The door for PLACEMENT and CROSS-DOCUMENT COMPARISON - client SYS-05's
    "map these terms into the Automobile family before cross-document
    comparison". Deliberately NOT the door for "does this row grant or deny
    coverage": that stays `canon_line`, so a coverage part can never become
    independent evidence that a line exists or is denied.
    """
    return canon_line(text) or canon_part(text, present_families)


# ── THE LAYER OF AN UMBRELLA-FAMILY POLICY (6 Oct 2026, Choice Electric) ────
# "Excess" folds into UMBRELLA on purpose (C23: an excess policy must never
# masquerade as the primary line it sits over), and every reader - the carried
# lines, the ACORD 131 recommendation - keeps reading one family. But a tower
# is several POLICIES: an umbrella and an excess (following form) policy above
# it are two contracts, two carriers, two limits, and Brent's rule is one ACORD
# 131 each. The layer is what tells them apart where policies are counted (the
# line records, the Data Consistency picker); it never changes the family.
UMBRELLA_LAYER = "umbrella"
EXCESS_LAYER = "excess"


def umbrella_layer(text: Any) -> Optional[str]:
    """The layer an umbrella-family line name prints, or None for any other line.

    "excess" when the name names an excess / following-form policy and not an
    umbrella ("Excess (Following Form) Liability", "Commercial Excess
    Liability"); "umbrella" otherwise ("Commercial Liability Umbrella",
    "Excess Umbrella" - a name that says umbrella is the umbrella layer)."""
    if canon_line(text) != UMBRELLA:
        return None
    s = _clean(text)
    if re.search(r"\bumbrella\b", s):
        return UMBRELLA_LAYER
    if re.search(r"\bexcess\b|\bexlia\b|\bfollow(?:ing|s)? form\b", s):
        return EXCESS_LAYER
    return UMBRELLA_LAYER


def is_known_family(token: Any) -> bool:
    """True when ``token`` is one of the family constants this module emits."""
    return token in _ALL_FAMILIES


_ALL_FAMILIES = frozenset({
    GENERAL_LIAB, AUTO, UMBRELLA, WORKERS_COMP, PROPERTY, INLAND_MARINE, CRIME,
    CYBER, PROFESSIONAL, EPLI, POLLUTION, DIRECTORS_OFFICERS, EMPLOYEE_BENEFITS,
    LIQUOR,
})

# Families that are a STANDALONE liability line distinct from GL. Consumers
# that ask "is this a specialty leftover for the Other-policy row" use this
# instead of re-deriving it from token heuristics.
SPECIALTY_LIABILITY_FAMILIES = frozenset({
    PROFESSIONAL, EPLI, POLLUTION, DIRECTORS_OFFICERS, EMPLOYEE_BENEFITS, LIQUOR,
})

# A line WRITTEN AS PART of another line's policy when the same company writes
# both (Brent, 19 Oct 2026): "Employee Benefits Liability ... is generally
# written on ACORD 126 when written with GL" - a coverage of the GL policy, not
# a line of business of its own on ACORD 125's page 1. Read by
# `written_with_line`; a family with its own company stays a policy of its own.
WRITTEN_WITH: Dict[str, str] = {EMPLOYEE_BENEFITS: GENERAL_LIAB}


def written_with_line(family: Optional[str], carrier: Any, rows: Any) -> Optional[str]:
    """The line whose policy ``family`` is written as part of - WRITTEN_WITH's
    parent when ``rows`` (coverage rows, {"line", "carrier"}) hold a policy of
    that line written by the same company (or either prints no company) - else
    None. Never raises."""
    parent = WRITTEN_WITH.get(str(family or ""))
    if not parent:
        return None
    try:
        from services.normalization import strict_entity_key as _ek
    except Exception:                                         # noqa: BLE001
        return None
    own = _ek(str(carrier or ""))
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or canon_line(str(r.get("line") or "")) != parent:
            continue
        theirs = _ek(str(r.get("carrier") or ""))
        if not own or not theirs or own == theirs:
            return parent
    return None


# ── EXPLICIT DENIAL OF A LINE (client 1.7 "Active vs. Listed Coverage") ──────
# *"A section existing in a policy package does not mean coverage is active. A
# section marked No Coverage must not become an active line of business."*
#
# The regex lived in `extraction_service` and is imported back from here, so
# there is exactly ONE definition of what a denial phrase looks like. It is
# NARROW on purpose: a bare "none" appears all over a declarations page, and a
# Cyber EXCLUSION printed inside a GL form does not deny the GL line.
COVERAGE_DENIAL_RE = re.compile(
    r"no\s+coverage|not\s+covered|coverage\s+not\s+provided|no\s+coverage\s+provided",
    re.I,
)

# Keys on a `coverage_lines` entry that can carry a denial phrase. `line` is
# deliberately absent: the line NAME is the subject of the sentence, never the
# verdict on it, and a carrier legitimately named "... Casualty - No Coverage
# Section" would otherwise deny itself.
_DENIAL_BEARING_KEYS: Tuple[str, ...] = (
    "premium", "limit", "status", "coverage", "note", "remarks",
)


def denies_coverage(entry: Any) -> bool:
    """True when a ``coverage_lines`` entry EXPLICITLY says the line is absent.

    THE TWIN OF "grants", AND NOT ITS NEGATION - the distinction is the whole
    point (V1 C1-K). A certificate of insurance never prints premiums, so most
    COI rows grant nothing; reading that as a DENIAL is Principle 3's forbidden
    move and it manufactured a false "lines of business differ" warning inside
    the very fix meant to enforce Principle 3.

        grants  -> a premium or limit is present   = positive proof of coverage
        denies  -> a detail literally says NO      = positive proof of absence
        neither -> the document is SILENT
    """
    if not isinstance(entry, dict):
        return False
    for key in _DENIAL_BEARING_KEYS:
        val = entry.get(key)
        if val is not None and COVERAGE_DENIAL_RE.search(str(val)):
            return True
    return False


def denied_families(coverage_lines: Any) -> frozenset:
    """Canonical families this package EXPLICITLY declares it does not carry.

    Positive evidence on both sides, and a denial is withdrawn the moment any
    entry grants the same family - two sources disagreeing about whether a
    coverage exists is a CONFLICT for the producer (client 1.7's acceptance
    criterion), never a quiet "not applicable".

    Returns an empty set for anything it cannot read, so a package with no
    ``coverage_lines`` behaves exactly as it does today.
    """
    denied: set = set()
    granted: set = set()
    if not isinstance(coverage_lines, list):
        return frozenset()
    for entry in coverage_lines:
        if not isinstance(entry, dict):
            continue
        fam = canon_line(entry.get("line"))
        if not fam:
            continue                      # unmapped terminology: no opinion (1.7)
        if denies_coverage(entry):
            denied.add(fam)
        elif _grants_coverage(entry):
            granted.add(fam)
    return frozenset(denied - granted)


# A premium SUBTOTAL is a charge, not a coverage part. Live 15 Sep 2026, the
# Orbin auto declarations: "Premium for Attached Items 4, 5, and/or 6" and
# "Premium for Endorsements" came back as coverage rows carrying their $322 and
# $457, and reached the producer as "Coverage part not recognised" - asking
# someone which LINE a subtotal belongs to. A line NAME that names money names a
# charge; the extraction prompt's own RULE 16 draws the same line for the
# premium column (fees, surcharges, taxes). No line of business is called
# "premium" or "total".
_CHARGE_LABEL_RE = re.compile(
    r"\b(?:premiums?|fees?|surcharges?|tax(?:es)?|subtotal)\b|^\s*total\b", re.I)


def is_charge_label(text: Any) -> bool:
    """True when a coverage-row NAME is a charge (a premium, fee, tax or total)."""
    return bool(_CHARGE_LABEL_RE.search(str(text or "")))


# A CONTAINER names the policy, not a coverage: "Commercial Package", "CPP",
# "Commercial Multiple Peril", an AMS code "CPKGE". It holds several lines, so
# it maps to no family (blank over wrong), and it is not unknown terminology
# either. Live 5 Oct (CH125): the AMS export's package row became "Coverage
# part not recognised" beside the property row printing the same number. The
# generality audit (G3) widened the vocabulary and the shapes: an appended
# status / code / carrier ("(Expiring)", "- Magnolia Underwriters"), OCR glued
# words, and branded packages ("Contractors Package Policy"). A Businessowners
# policy is a LINE, never a container.
_CONTAINER_STRONG = frozenset({"package", "packaged", "pkg", "cpp", "cpkge", "cmp", "smp",
                               "portfolio", "multiperil"})
_CONTAINER_WORDS = _CONTAINER_STRONG | frozenset({"multi", "multiple", "peril", "combination"})
_CONTAINER_FILLER = frozenset({"commercial", "business", "policy", "insurance",
                               "coverage", "program", "programme", "special", "line",
                               "lines", "and", "the"})


def _container_text(text: Any) -> str:
    s = re.sub(r"\([^)]*\)", " ", str(text or ""))           # "(Expiring)", "(CPKGE)"
    s = re.split(r"\s[-–—]\s", s)[0]                # "CPP - Magnolia Underwriters"
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)               # OCR "CommercialPackage"
    return _clean(s)


def is_container_label(text: Any) -> bool:
    """True when a coverage-row NAME is a package / multi-peril policy container."""
    words = _container_text(text).split()
    if not words:
        return False
    named = [w for w in words if w not in _CONTAINER_FILLER]
    if named and all(w in _CONTAINER_WORDS for w in named) and (
            set(named) & _CONTAINER_STRONG
            or ("peril" in named and ({"multi", "multiple"} & set(named)))):
        return True
    # A branded package: "Contractors Package Policy", "Hospitality Package".
    return bool(re.search(r"\b(?:package|pkg)(?:\s+(?:policy|program|programme))?$",
                          " ".join(words))) and "protection" not in words


def _same_contract_number(a: str, b: str) -> bool:
    """Two punctuation-blind policy numbers name one contract: equal, or one is
    the other plus a short module / term suffix ("CP123" vs "CP12300")."""
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 5 and long_.startswith(short) and len(long_) - len(short) <= 3


def unmapped_material_lines(coverage_lines: Any, part_lines: Any = None) -> list:
    """Line names this module cannot place that the package actually CARRIES.

    Client 1.7, the half that was never built: *"If terminology is not covered
    by a known normalization rule, do not automatically assume equivalence.
    Leave it unmapped **or route it for producer review when material**."*
    Leaving it unmapped was done from day one - `canon_line` returns None and
    every call site skips it. Nothing ever routed it anywhere, so an
    unrecognised coverage part was silently invisible.

    MATERIAL means the package's own documents show the line is CARRIED - a
    premium or a limit on the entry, the same positive-evidence test
    `denied_families` uses to withdraw a denial. A row with no premium and no
    limit is a certificate row or a placeholder; surfacing those would put a
    review item on every ordinary COI (D26: silence is not evidence).

    PLACED BY ITS DOCUMENT OR BY THE PRODUCER (14 Oct 2026, see the block below
    `_grants_coverage`): a row its own single-line declarations attribute to
    their line (`PART_OF_KEY`), and a part the producer answered
    (`part_lines`, the stored `PART_LINES_FACT`), is placed and not routed.

    Returns the ORIGINAL printed names, de-duplicated, in first-seen order -
    the producer needs to see the phrase the document actually used. Returns
    [] for anything it cannot read, so a package with no `coverage_lines`
    behaves exactly as it does today.
    """
    out: list = []
    seen: set = set()
    if not isinstance(coverage_lines, list):
        return out
    answers = parse_part_lines(part_lines)
    # One printing attributed by its own declarations places every printing of
    # that name (the same coverage part read again off another document).
    attributed = {_dedupe_key(e.get("line")) for e in coverage_lines
                  if isinstance(e, dict) and is_known_family(e.get(PART_OF_KEY))} - {""}

    def _placed_by_document_or_producer(entry: dict, raw: str) -> bool:
        if is_known_family(entry.get(PART_OF_KEY)) or _dedupe_key(raw) in attributed:
            return True
        return bool(answers) and part_key(raw) in answers

    # SYS-05: a coverage PART is placeable even though it does not NAME a line,
    # so it is not "terminology not covered by a known rule" and must not reach
    # the producer as one. Resolved against the families this package's own
    # rows establish, so an ambiguous part with no parent line is still routed.
    present = coverage_families_present(coverage_lines)
    by_policy = policy_number_families(coverage_lines)
    # Policy numbers some PLACED row carries. A container row sharing one is
    # that contract's own heading, already represented by its lines. A package
    # number usually spans two families, so `by_policy` (one family only)
    # cannot answer this.
    placed = [
        e for e in coverage_lines
        if isinstance(e, dict) and not is_container_label(e.get("line"))
        and (canon_line(e.get("line"))
             or canon_part(e.get("line"), present, by_policy.get(_policy_key(e))))
    ]
    placed_numbers = {_policy_key(e) for e in placed if _policy_key(e)}
    placed_carriers = {_clean(e.get("carrier")) for e in placed if _clean(e.get("carrier"))}

    def _container_is_placed(entry: dict) -> bool:
        key = _policy_key(entry)
        if key:
            return any(_same_contract_number(key, n) for n in placed_numbers)
        # No number (a premium summary, a certificate row): the carrier a placed
        # line also names ties it to that contract.
        return bool(_clean(entry.get("carrier")) and _clean(entry.get("carrier")) in placed_carriers)
    for entry in coverage_lines:
        if not isinstance(entry, dict):
            continue
        raw = str(entry.get("line") or "").strip()
        if not raw:
            continue
        if is_charge_label(raw):
            continue                      # a premium subtotal, not a coverage
        if canon_line(raw) or canon_part(raw, present, by_policy.get(_policy_key(entry))):
            continue                      # we can place it
        if is_container_label(raw) and _container_is_placed(entry):
            continue                      # the contract's heading; its lines are placed
        if _placed_by_document_or_producer(entry, raw):
            continue                      # its own declarations or the producer placed it
        if not _grants_coverage(entry):
            continue                      # not carried -> not material
        key = _dedupe_key(raw)
        if key and key not in seen:
            seen.add(key)
            out.append(raw)
    return out


# Connector words carry no meaning for "is this the same line printed twice?".
# `_clean` turns "&" into a space, so "Kidnap & Ransom" and "Kidnap and Ransom"
# differ by exactly one of these - and listing one coverage part twice in a
# review item makes it look like two problems.
_DEDUPE_STOPWORDS = frozenset({"and", "of", "the", "or"})


def _dedupe_key(text: Any) -> str:
    return " ".join(t for t in _clean(text).split() if t not in _DEDUPE_STOPWORDS)


def _grants_coverage(entry: dict) -> bool:
    """A premium or a limit on the entry is positive proof the line is carried.

    Deliberately a LOCAL, minimal reading rather than an import of
    ``extraction_service._line_entry_grants_coverage``: this leaf must not
    import the service layer, and it is used here only to WITHDRAW a denial -
    the failure mode of reading it too generously is that a denial is dropped
    and the fact stays ``not_stated``, i.e. today's behaviour.

    A line the PRODUCER added ("Policies in this submission", 7 Oct 2026,
    marked ``_producer_added``) is carried by their own statement.
    """
    if entry.get("_producer_added"):
        return True
    for key in ("premium", "limit"):
        val = entry.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if not text or COVERAGE_DENIAL_RE.search(text):
            continue
        if any(ch.isdigit() for ch in text):
            return True
    return False


# ── A COVERAGE PART PLACED BY ITS DOCUMENT OR BY THE PRODUCER (14 Oct 2026) ──
# Owner, live package 91c865a5 (Choice Electric): the Cyber policy's own
# declarations print its insuring agreements as rows - "Non-Panel Response
# Provider", "Digital Data Recovery", "Network Extortion", "Payment Card Loss",
# "Regulatory Proceeding", "Electronic, Social And Printed Media Liability" -
# each with its own limit, and all six reached the producer as "Coverage part
# not recognised ... no normalization rule" over a note saying we could not
# tell which line they belong to. They are not unknown terminology. A
# declarations page that names ONE line prints that line's coverage grid, so a
# row of it this module cannot otherwise place is a PART of that line - the
# same idea as `extraction_service.attach_generic_rows_to_document_line`.
#
# Two ways a row is placed, both read by `unmapped_material_lines` ONLY:
#   * by its DOCUMENT - `attribute_parts_to_document_line` marks the row
#     `PART_OF_KEY` (per document, in the merge's pre-pass);
#   * by the PRODUCER - the card offers the standard lines plus "Part of another
#     policy"; the answer is the fact `PART_LINES_FACT`, keyed by `part_key`.
#
# NEITHER IS EVIDENCE OF A LINE. The marker and the answer never reach
# `canon_line` / `canon_part` / `coverage_families_present` /
# `evidenced_line_families`, so no family is created, no line becomes carried
# and the form recommender cannot move. A part is placed for the producer
# review, never promoted (a new family is a product decision - D9).
PART_OF_KEY = "_part_of"
PART_LINES_FACT = "coverage_part_lines"
PART_OF_ANOTHER_POLICY = "other_policy"
PART_OF_ANOTHER_POLICY_LABEL = "Part of another policy - not a separate line"

# The choice list's words, one per family this module knows - and nothing else:
# a producer places a part on a line the canon already has.
FAMILY_LABELS: Dict[str, str] = {
    GENERAL_LIAB:       "General Liability",
    AUTO:               "Commercial Auto",
    PROPERTY:           "Commercial Property",
    WORKERS_COMP:       "Workers Compensation",
    UMBRELLA:           "Umbrella / Excess Liability",
    INLAND_MARINE:      "Inland Marine",
    CRIME:              "Crime",
    CYBER:              "Cyber",
    PROFESSIONAL:       "Professional Liability",
    EPLI:               "Employment Practices Liability",
    POLLUTION:          "Pollution Liability",
    DIRECTORS_OFFICERS: "Directors and Officers",
    EMPLOYEE_BENEFITS:  "Employee Benefits Liability",
    LIQUOR:             "Liquor Liability",
}
_PART_LINE_TOKENS = frozenset(FAMILY_LABELS) | {PART_OF_ANOTHER_POLICY}
_PART_KEY_RE = re.compile(r"^[0-9a-f]{10}$")


def part_key(name: Any) -> str:
    """Stable key for one coverage-part NAME: its de-duplicated wording, hashed
    (so "Kidnap & Ransom" and "Kidnap and Ransom" share one). Hex only, so a
    stored answer never carries the printed words through the answer readers.
    "" for a name with no words."""
    key = _dedupe_key(name)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10] if key else ""


def parse_part_lines(value: Any) -> Dict[str, str]:
    """The producer's answers, {part key: family or PART_OF_ANOTHER_POLICY},
    read from the stored fact - an envelope, its text ("key=line; key=line") or
    a dict. A pair that does not read is left out; never raises."""
    if isinstance(value, dict) and "value" in value:
        value = value.get("value")
    pairs: list = []
    if isinstance(value, dict):
        pairs = list(value.items())
    elif isinstance(value, str):
        for chunk in value.split(";"):
            k, sep, v = chunk.partition("=")
            if sep:
                pairs.append((k, v))
    out: Dict[str, str] = {}
    for k, v in pairs:
        k, v = str(k or "").strip().lower(), str(v or "").strip().lower()
        if _PART_KEY_RE.match(k) and v in _PART_LINE_TOKENS:
            out[k] = v
    return out


def format_part_lines(answers: Any) -> str:
    """The stored text for a set of answers - sorted, so one set has one text."""
    clean = parse_part_lines(dict(answers) if isinstance(answers, dict) else answers)
    return "; ".join(f"{k}={clean[k]}" for k in sorted(clean))


def is_valid_part_lines(text: Any) -> bool:
    """FACT_REGISTRY's validator for `PART_LINES_FACT`: at least one pair, and
    every pair names a part key and a line this module knows."""
    s = str(text or "").strip()
    chunks = [c for c in s.split(";") if c.strip()]
    return bool(chunks) and len(parse_part_lines(s)) == len(chunks)


def part_line_choices(present_families: Any = ()) -> List[Dict[str, str]]:
    """The choice list for "which line is this coverage part of?": the standard
    lines - the ones this package already carries first - then "Part of
    another policy". `value` is the family token the answer stores."""
    try:
        present = set(present_families or ())
    except TypeError:                                        # pragma: no cover
        present = set()
    order = ([f for f in FAMILY_LABELS if f in present]
             + [f for f in FAMILY_LABELS if f not in present])
    out = [{"value": f, "label": FAMILY_LABELS[f]} for f in order]
    out.append({"value": PART_OF_ANOTHER_POLICY, "label": PART_OF_ANOTHER_POLICY_LABEL})
    return out


def attribute_parts_to_document_line(rows: Any) -> List[str]:
    """Mark ONE document's unplaceable rows as parts of the one line it names.

    `rows` is that document's own `coverage_lines`, mutated in place (each
    attributed row gets `PART_OF_KEY` = the family); returns the names marked.

    The document's line: the families its rows NAME (`canon_line`, a denied or
    container row aside), or - when no row names a line - the families its
    unambiguous parts establish. Exactly one, or nothing is marked: a package
    policy names several lines and its unknown rows stay for the producer.

    A row is attributed only when nothing contradicts it belonging to that
    line's contract: a policy number of its own that is not the line's, or a
    carrier other than the line's, keeps it out (another policy printed on the
    same page). A row any rule here already places keeps its own placement, so
    a known part ("Business Interruption") is never re-attributed.
    """
    if not isinstance(rows, list):
        return []
    rows = [r for r in rows if isinstance(r, dict)]
    if len(rows) < 2:
        return []
    # The rows that say which line this document is: the ones NAMING a line,
    # or - when none does - its unambiguous parts ("Collision", "Towing").
    anchors = [r for r in rows
               if canon_line(r.get("line")) and not denies_coverage(r)
               and not is_container_label(r.get("line"))]
    families = {canon_line(r.get("line")) for r in anchors}
    if not families:
        anchors = [r for r in rows if canon_part(r.get("line")) and not denies_coverage(r)]
        families = {canon_part(r.get("line")) for r in anchors}
    if len(families) != 1:
        return []
    family = next(iter(families))
    present = coverage_families_present(rows)
    by_policy = policy_number_families(rows)
    line_numbers = {_policy_key(r) for r in anchors if _policy_key(r)}
    line_carriers = {_clean(r.get("carrier")) for r in anchors if _clean(r.get("carrier"))}
    marked: List[str] = []
    for r in rows:
        raw = str(r.get("line") or "").strip()
        if not raw or not _dedupe_key(raw):
            continue
        if canon_line(raw) or is_charge_label(raw) or is_container_label(raw):
            continue
        if canon_part(raw, present, by_policy.get(_policy_key(r))):
            continue                     # a known part keeps its own placement
        num = _policy_key(r)
        if num and line_numbers and not any(_same_contract_number(num, n) for n in line_numbers):
            continue                     # another contract printed on this page
        car = _clean(r.get("carrier"))
        if car and line_carriers and car not in line_carriers:
            continue                     # another company's policy
        r[PART_OF_KEY] = family
        marked.append(raw)
    return marked


# ── WHICH LINES DOES THIS SUBMISSION ACTUALLY CARRY? ─────────────────────────
# Client audit 2026-09-11, item 2: *"Primble is identifying coverages that
# Orbin does not actually have (this is coming from language in the policy
# booklet). The cover page lists Property, Crime, WC, Farm, Liquor, EPLI, OCP
# ... Coverage should require affirmative evidence."*
#
# ROOT CAUSE. The package carries TWO coverage facts and only one of them has
# ever had a definition:
#
#   `coverage_lines`      structured, and gated - a line counts when it carries
#                         a premium or a limit (`_line_entry_grants_coverage`).
#   `lines_of_business`   a bare `[string]` in the extraction schema with NO
#                         rule in the prompt at all, unioned across every
#                         document chunk, so one mention anywhere in 271 pages
#                         sticks for good.
#
# The standard ISO endorsement header is a MENU of what the endorsement could
# attach to -
#
#   "THIS ENDORSEMENT MODIFIES INSURANCE PROVIDED UNDER THE FOLLOWING:
#    COMMERCIAL PROPERTY ... CRIME AND FIDELITY ... FARM ... LIQUOR LIABILITY
#    ... EMPLOYMENT-RELATED PRACTICES ... OWNERS AND CONTRACTORS PROTECTIVE"
#
# - and we read it as an inventory of what the applicant owns. The client's
# list is that boilerplate word for word.
#
# The corroboration rule already existed, INLINE, inside the ACORD 125
# checkbox resolver (`pdf_service._derive_indicator`, 2026-08-10). It was never
# available to the cover page, the scorer or the recommender, so the same
# phantom line was refused on the form and printed on the cover of the same
# package. This is that rule, extracted, canonical rather than substring, and
# with three more sources of evidence.
#
# WHAT THIS IS NOT: a filter on the fact. `lines_of_business` keeps every name
# the documents printed - it is the MENTION record, and the questionnaire, the
# unmapped-line advisory and the conflict picker all still read it. This
# answers the different question that display and scoring should have been
# asking all along.

def _flag_families(flags: Any) -> frozenset:
    """Canonical line families whose coverage flag is TRUE.

    The mapping is DERIVED from the flag's own name (`has_property_coverage`
    -> "property coverage" -> ``property``), not from a table that would have
    to be maintained beside the flags themselves. A flag whose name names no
    line simply contributes nothing.
    """
    out: set = set()
    if not isinstance(flags, dict):
        return frozenset()
    for name, value in flags.items():
        if value is not True:
            continue
        # Only a LINE flag (`has_<line>`) names a line. A SUB-flag describes a
        # feature of a line - `property_has_bi_coverage`, `auto_has_um_uim` -
        # and was read as the line itself: on the live Orbin package business-
        # income wording "evidenced" a Property line its declarations deny
        # (client 2026-09-11 item 9). No `is_*` flag names a line either.
        m = re.match(r"^has[_\s]+(.+)$", str(name or ""))
        if not m:
            continue
        fam = canon_line(m.group(1).replace("_", " "))
        if fam:
            out.add(fam)
    return frozenset(out)


def _flag_denied_families(flags: Any) -> frozenset:
    """Canonical line families whose `has_<line>` flags are explicitly FALSE,
    with none of them true.

    A false line flag is the strong half of a coverage flag (`line_presence`
    reads it the same way): extraction saw no evidence of the line anywhere,
    or the declarations deny it and `apply_declared_absent_downgrades` turned
    it off. On the live Orbin package all three denied lines - Property, Crime
    and Workers' Compensation - are false here, and the verdict survives the
    dec-index purge because flags are never purged.
    """
    if not isinstance(flags, dict):
        return frozenset()
    said: dict = {}
    for name, value in flags.items():
        m = re.match(r"^has[_\s]+(.+)$", str(name or ""))
        if not m:
            continue
        fam = canon_line(m.group(1).replace("_", " "))
        if not fam:
            continue
        if value is True:
            said[fam] = True
        elif value is False and said.get(fam) is not True:
            said[fam] = False
    return frozenset(f for f, v in said.items() if v is False)


def carried_lines_of_business(facts: Any, flags: Any = None) -> list:
    """The lines of business the submission has AFFIRMATIVE evidence for, as
    the documents printed them.

    Evidence, any one of which is enough (deliberately permissive - this can
    only ever DROP a line nothing corroborates):

      1. a `coverage_lines` row that GRANTS the same canonical line
         (a premium or a limit);
      2. a `coverage_lines` row that IDENTIFIES a policy on it - a NAIC or its
         own policy number. Added 2026-09-11 for the same reason the
         stamping layer needed it: a declarations page showing ONE package
         total leaves every row unpriced, and a line with its own policy
         number is plainly carried. A carrier NAME alone is a mention (14 Sep,
         live Orbin shape - see `_row_identifies_policy`);
      3. a `has_<line>` coverage FLAG set true by extraction (never a
         sub-flag such as `property_has_bi_coverage`);
      4. the family is named by a granting row under a DIFFERENT spelling -
         covered by (1), since both sides canonicalise.

    NO PER-LINE EVIDENCE AT ALL -> the raw list is returned unchanged. That is
    the legacy branch and it is load-bearing: a package whose `coverage_lines`
    never arrived must not have its whole coverage inventory blanked. Positive
    evidence only, in both directions.

    A name this module cannot place (`Farm`, `Owners and Contractors
    Protective`) can never be corroborated, so it is dropped from the CARRIED
    list - and `unmapped_material_lines` still routes it to the producer, which
    is where an unrecognised coverage part belongs (Principle 7).
    """
    raw = facts.get("lines_of_business") if isinstance(facts, dict) else None
    if isinstance(raw, dict) and "value" in raw:
        raw = raw.get("value")
    if not isinstance(raw, list) or not raw:
        return []
    names = [str(x).strip() for x in raw if str(x or "").strip()]

    # One evidence reading, shared with `line_is_carried` and the 125 boxes
    # (see `evidenced_line_families` / `_row_evidence`). A premium or a limit is
    # money changing hands and outranks a false flag; identity alone never
    # overrides an explicitly false `has_<line>` flag (the live extraction put
    # the Inland Marine number on the Property, Crime and WC rows the
    # declarations deny).
    evidenced, _rows_exist = evidenced_line_families(facts, flags)

    if not evidenced:
        # No AFFIRMATIVE per-line evidence for anything - the legacy raw list,
        # less any line explicitly denied: by a false `has_<line>` flag (the fuzz
        # found this branch printing a line its own flag had turned off) or by a
        # "NO COVERAGE" row. Rows that only DENY are not evidence FOR the other
        # mentions, so they cannot drop them (24 Sep 2026: a declarations page
        # whose one row denied Property lost its General Liability mention, and
        # the Property contradiction with the application went silent).
        denied = set(_flag_denied_families(flags))
        _rows = facts.get("coverage_lines") if isinstance(facts, dict) else None
        if isinstance(_rows, dict) and "value" in _rows:
            _rows = _rows.get("value")
        for _e in _rows if isinstance(_rows, list) else []:
            if isinstance(_e, dict) and denies_coverage(_e):
                _fam = canon_line(_e.get("line"))
                if _fam:
                    denied.add(_fam)
        return _one_name_per_line([n for n in names if canon_line(n) not in denied])

    kept, dropped = [], []
    for name in names:
        fam = canon_line(name)
        (kept if (fam and fam in evidenced) else dropped).append(name)
    if dropped:
        logger.info(
            "carried_lines_of_business: %d mentioned line(s) have no coverage "
            "evidence and are not reported as carried - %s",
            len(dropped), ", ".join(dropped[:6]))
    return _one_name_per_line(kept)


def evidenced_line_families(facts: Any, flags: Any = None) -> Tuple[set, bool]:
    """(families the package has AFFIRMATIVE evidence for, per-line rows exist).

    The evidence `carried_lines_of_business` applies - a granting row, a row
    identifying its own policy unless a false flag denies the line, or a true
    `has_<line>` flag - exposed as FAMILIES, so a caller holding a fact rather
    than a line name asks the same question the cover page asks.
    """
    lines = facts.get("coverage_lines") if isinstance(facts, dict) else None
    if isinstance(lines, dict) and "value" in lines:
        lines = lines.get("value")
    rows = [e for e in lines if isinstance(e, dict)] if isinstance(lines, list) else []
    evidenced: set = set(_flag_families(flags))
    granted, identified = _row_evidence(rows)
    evidenced |= granted
    evidenced |= (identified - _flag_denied_families(flags))
    return evidenced, bool(rows)


def _contract_key(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(value or "")).upper()


def _same_contract_key(a: str, b: str) -> bool:
    """One contract printed with and without its term marker (BBC7263 /
    BBC7263-26, 6E74002 / 6E7-40-02---26): equal, or one a 6+ character
    prefix of the other."""
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 6 and long_.startswith(short)


def _row_evidence(rows: list) -> Tuple[set, set]:
    """(families a row GRANTS, families a row IDENTIFIES) - one reading for
    the cover page, the scorer and ACORD 125's line-of-business boxes.

    Identity is narrower than it was, on two measured shapes (24 Sep 2026):
      * a BORROWED number is not identity. An endorsement-menu row ("Liquor
        Liability Coverage Part") carrying the GL policy's own number is a
        coverage PART of that policy - the number is already owned by a
        granting row of a DIFFERENT line. Before this, one footer number put
        Liquor and Pollution on the cover and ticked them on the 125;
      * a NAIC with no number of the row's own identifies a line only on a
        package where NO row is priced. A NAIC is the carrier's, and the
        menu rows carry the carrier.
    """
    granted: set = set()
    owners: list = []                  # (contract key, family) of granting rows
    for entry in rows:
        fam = canon_line(entry.get("line"))
        if not fam or denies_coverage(entry):
            continue
        if _grants_coverage(entry):
            granted.add(fam)
            k = _contract_key(entry.get("policy_number"))
            if k:
                owners.append((k, fam))
    any_priced = bool(granted)
    identified: set = set()
    for entry in rows:
        fam = canon_line(entry.get("line"))
        if not fam or denies_coverage(entry) or _grants_coverage(entry):
            continue
        if not _row_identifies_policy(entry):
            continue
        num = str(entry.get("policy_number") or "").strip()
        own_number = bool(num and num.lower() not in _IDENTITY_PLACEHOLDERS
                          and not COVERAGE_DENIAL_RE.search(num))
        if own_number:
            k = _contract_key(num)
            if any(_same_contract_key(k, ok) and of != fam for ok, of in owners):
                continue                   # another line's policy - a coverage part
            identified.add(fam)
        elif not any_priced:
            identified.add(fam)            # NAIC only, on an unpriced package
    return granted, identified


def line_is_carried(family: Optional[str], facts: Any, flags: Any = None) -> Optional[bool]:
    """Is this canonical line carried by the package? True / False / None.

    False needs POSITIVE evidence of absence: its `has_<line>` flag is
    explicitly false, or the package has a per-line inventory and nothing in
    it evidences this line. None - cannot tell - when there is no per-line
    evidence at all, and a caller must read None as "keep today's behaviour".
    """
    if not family:
        return None
    if family in _flag_denied_families(flags):
        return False
    evidenced, rows_exist = evidenced_line_families(facts, flags)
    if family in evidenced:
        return True
    if rows_exist and evidenced:
        return False
    return None


# Fact-key PREFIX -> the line the fact describes. Derived from the fact
# registry's own naming convention; a key with no line prefix is not judged.
_FACT_PREFIX_FAMILY: Tuple[Tuple[str, str], ...] = (
    ("property_", "property"), ("gl_", "general_liab"), ("auto_", "auto"),
    ("umbrella_", "umbrella"), ("wc_", "workers_comp"), ("crime_", "crime"),
    ("inland_marine_", "inland_marine"), ("liquor_", "liquor"),
    ("epli_", "epli"), ("cyber_", "cyber"),
)


def fact_line_family(fact_key: Any) -> Optional[str]:
    """The line of business a canonical FACT belongs to, or None.

    Prefixes first (`property_building_value` -> property), then the scorer's
    own coverage-gated table for the unprefixed property/COPE and WC keys
    (`year_built`, `construction_type`, `employers_liability_limits` ...), so
    this and the SQS relevance gate read one declaration."""
    k = str(fact_key or "").strip().lower()
    if not k or k.startswith("_"):
        return None
    for prefix, fam in _FACT_PREFIX_FAMILY:
        if k.startswith(prefix):
            return fam
    try:
        from services.sqs_service import _COVERAGE_GATED_FACT_FLAGS as _gated
        flag = _gated.get(k)
    except Exception:                                        # noqa: BLE001
        flag = None
    if flag:
        m = re.match(r"^has[_\s]+(.+)$", flag)
        return canon_line(m.group(1).replace("_", " ")) if m else None
    return None


def _one_name_per_line(names: list) -> list:
    """One entry per line of business: its FIRST printing, in document order.

    Live 15 Sep 2026, the client's own Orbin policy: the cover page listed TEN
    names for four lines - "Automobile", then "Commercial Auto"; "Umbrella",
    "Commercial Umbrella" and "Commercial Liability Umbrella"; "Inland Marine",
    "Commercial Inland Marine" and "Computer Coverage" (an inland marine
    coverage part). Every one was correctly evidenced; nothing asked whether two
    names were the same line. The canonical family is that question's one door.
    A name no rule places is its own line, de-duplicated by spelling only.
    """
    out: list = []
    seen: set = set()
    for name in names:
        key = canon_line(name) or ("unplaced", _dedupe_key(name))
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


# Placeholder text a model writes into an identity box when the row has none.
_IDENTITY_PLACEHOLDERS = frozenset({"n/a", "na", "none", "null", "unknown", "-", "--"})


def _row_identifies_policy(entry: dict) -> bool:
    """A NAIC code or the row's OWN policy number - the contract behind the line.

    A carrier NAME alone is a mention, not a policy (client 2026-09-11 item 9,
    measured on the live Orbin package). Extraction attached "Employers Mutual
    Casualty Company" to all 13 rows it lifted from ISO endorsement menus and to
    the three lines the declarations deny, none with a premium or a number, and
    this test kept every one - Property, Crime, Workers' Compensation, Liquor
    and Pollution stayed on the cover page. A real line that prints no premium
    still names its contract: a certificate row carries a NAIC and a number, a
    narrative row a number. Kept local for the leaf rule (see `_grants_coverage`
    for why). Reading it narrowly can only drop a line nothing else
    corroborates, and the scorer also reads the `has_<line>` flags.
    """
    for key in ("naic", "policy_number"):
        text = str(entry.get(key) or "").strip()
        if (text and text.lower() not in _IDENTITY_PLACEHOLDERS
                and not COVERAGE_DENIAL_RE.search(text)):
            return True
    return False
