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

import logging
import re
from typing import Any, Optional, Tuple

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
    PROPERTY: ("property damage",),
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
    (EMPLOYEE_BENEFITS,  ("employee benefits",)),
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


def unmapped_material_lines(coverage_lines: Any) -> list:
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

    Returns the ORIGINAL printed names, de-duplicated, in first-seen order -
    the producer needs to see the phrase the document actually used. Returns
    [] for anything it cannot read, so a package with no `coverage_lines`
    behaves exactly as it does today.
    """
    out: list = []
    seen: set = set()
    if not isinstance(coverage_lines, list):
        return out
    # SYS-05: a coverage PART is placeable even though it does not NAME a line,
    # so it is not "terminology not covered by a known rule" and must not reach
    # the producer as one. Resolved against the families this package's own
    # rows establish, so an ambiguous part with no parent line is still routed.
    present = coverage_families_present(coverage_lines)
    by_policy = policy_number_families(coverage_lines)
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
    """
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

    lines = facts.get("coverage_lines") if isinstance(facts, dict) else None
    if isinstance(lines, dict) and "value" in lines:
        lines = lines.get("value")
    rows = [e for e in lines if isinstance(e, dict)] if isinstance(lines, list) else []
    evidenced: set = set(_flag_families(flags))
    granted: set = set()
    identified: set = set()
    for entry in rows:
        fam = canon_line(entry.get("line"))
        if not fam or denies_coverage(entry):
            continue
        if _grants_coverage(entry):
            granted.add(fam)
        elif _row_identifies_policy(entry):
            identified.add(fam)
    # A premium or a limit is money changing hands and outranks a false flag.
    # A policy number only IDENTIFIES a contract, and the live extraction put
    # the Inland Marine number on the Property, Crime and Workers' Compensation
    # rows the declarations deny - so identity alone never overrides an
    # explicitly false `has_<line>` flag.
    evidenced |= granted
    evidenced |= (identified - _flag_denied_families(flags))

    if not rows and not evidenced:
        # No per-line evidence FOR anything - the legacy raw list, less any line
        # an explicitly false `has_<line>` flag denies. A false flag is positive
        # evidence of absence, not silence; the fuzz found this branch printing
        # a line its own flag had turned off.
        denied = _flag_denied_families(flags)
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
