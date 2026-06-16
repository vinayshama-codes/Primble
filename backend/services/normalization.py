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
from typing import Any, List, Optional, Set

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
})
FEIN_FIELDS = frozenset({"fein", "fein_ssn", "tax_id"})


def is_carrier_field(field: str) -> bool:
    return field in CARRIER_FIELDS


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
    "bi": "bi",
    "building": "bi",
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
    """Lowercase, replace '&' with 'and', drop punctuation, collapse whitespace."""
    if s is None:
        return ""
    s = str(s).lower().replace("&", " and ")
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
    """Entity-type to a canonical token. "LLC" == "Limited Liability Company"."""
    s = _basic(value)
    if not s:
        return ""
    for variant, canon in _ENTITY_TYPE_SYNONYMS_SORTED:
        s = re.sub(rf"\b{re.escape(variant)}\b", canon, s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_address(value: Any) -> str:
    """Street address for comparison.

    Lowercases, treats '#' as a separator, drops punctuation, maps street-suffix
    words to their abbreviation (Street->st, Avenue->ave, ...), and removes unit
    markers (Suite/Ste/Unit/#) so "4800 DAHLIA ST #D13" and "4800 Dahlia Street
    D13" both reduce to "4800 dahlia st d13".
    """
    if value is None:
        return ""
    s = str(value).lower().replace("#", " ")
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    tokens = s.split()
    out: List[str] = []
    for tok in tokens:
        if tok in _UNIT_MARKERS:
            continue
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


def normalize_fein(value: Any) -> str:
    """Digits-only FEIN. Returns '' when fewer than 9 digits (incomplete)."""
    if value is None:
        return ""
    digits = re.sub(r"\D", "", str(value))
    return digits if len(digits) >= 9 else ""


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

def normalize_value(field: str, value: Any) -> str:
    """Return the canonical COMPARISON string for ``value`` given its fact key.

    '' means "no usable signal" — the caller should treat it as absent (not as a
    distinct value), so a missing/garbage value never manufactures a conflict.
    """
    if field in NAME_FIELDS:
        return normalize_name(value)
    if field in DATE_FIELDS:
        iso = normalize_date(value)
        # Unparseable dates fall back to general text so two genuinely different
        # un-date-like strings still differ rather than both collapsing to ''.
        return iso if iso is not None else normalize_general(value)
    if field in ENTITY_TYPE_FIELDS:
        return normalize_entity_type(value)
    if field in ADDRESS_FIELDS:
        return normalize_address(value)
    if field in CARRIER_FIELDS:
        return normalize_carrier(value)
    if field in FEIN_FIELDS:
        return normalize_fein(value)
    return normalize_general(value)


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
