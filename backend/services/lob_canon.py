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

import re
from typing import Any, Optional, Tuple

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
    (CRIME,         ("crime", "fidelity", "employee dishonesty", "employee theft")),
)

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
        if any(p in s for p in phrases):
            return key
    for key, phrases in _SPECIALTY:
        if any((p in s) if not p.endswith(" ") else (p in padded) for p in phrases):
            return key
    if any(p in s for p in _GL_PHRASES):
        return GENERAL_LIAB
    if "liability" in s.split() or "liab" in s.split():
        if set(s.split()) <= GL_GENERIC_TOKENS:
            return GENERAL_LIAB
        return None
    return None


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
    for entry in coverage_lines:
        if not isinstance(entry, dict):
            continue
        raw = str(entry.get("line") or "").strip()
        if not raw or canon_line(raw):
            continue                      # blank, or we can place it
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
