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
    "llc": "llc",
    "professional limited liability company": "pllc",
    "pllc": "pllc",
    "limited liability partnership": "llp",
    "llp": "llp",
    "limited partnership": "lp",
    "lp": "lp",
    "incorporated": "inc",
    "inc": "inc",
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
        return normalize_carrier(value)
    if field in FEIN_FIELDS:
        return normalize_fein(value)
    if field in VALUATION_METHOD_FIELDS:
        return normalize_valuation_method(value)
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
            tail = lowered[idx + len(phrase): idx + len(phrase) + 20].lstrip()
            if not any(tail.startswith(q) for q in _NO_LOSS_QUALIFIERS):
                return True
            start = idx + len(phrase)
    return False
