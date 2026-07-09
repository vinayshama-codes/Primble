"""display_canonicalizer.py

Presentation-grade canonicalization for values STAMPED onto ACORD forms.

WHY THIS IS SEPARATE FROM services/normalization.py
----------------------------------------------------
``normalization.py`` produces a *comparison key*. It is deliberately DESTRUCTIVE
- it drops entity suffixes ("Orbin Contracting LLC" -> "orbin contracting"),
strips unit markers ("Suite D13" -> "d13"), and lowercases everything - so that
two different *formats* of the same value compare equal and do not manufacture a
false cross-document conflict (Beta Report Test-Report.txt Sec 5). That output is
COMPARISON-ONLY and must never be printed on a form.

THIS module produces a *clean display value*. It is NON-DESTRUCTIVE: it
standardizes formatting only (casing, date format, street-suffix abbreviation,
currency grouping) while PRESERVING every piece of content - the "LLC" suffix,
the unit number, the ZIP+4. It is what gets stamped when
``ENABLE_DISPLAY_CANONICALIZATION`` is on.

Beta Report Sec 5.1 kept the RAW value visible in the review/picker UI; this
layer only changes what is printed on the generated PDF. The raw value stays in
the fact envelope / audit log, so raw remains one hover away for verification.

Design notes
------------
* PURE module - no DB, no I/O, no network, no imports from other services.
  Easy to unit-test.
* DEFENSIVE - every canonicalizer returns the ORIGINAL (whitespace-trimmed)
  string unchanged when it cannot confidently transform the value (an
  unparseable date, a non-numeric "amount", an unknown state). It never blanks
  or mangles a value it does not understand.
* CONTENT-PRESERVING - abbreviation/standardization only. No token is ever
  dropped (unlike the comparison normalizer). "Suite" becomes "Ste", never
  nothing; "LLC" is kept, never stripped.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

CANONICALIZER_MODEL_VERSION = "1.0.0"


# ── Reference maps ────────────────────────────────────────────────────────────

# Street-suffix full word -> Title-case abbreviation (Beta Report Sec 5.2:
# Street = St, Avenue = Ave, ...). Values are the DISPLAY form (kept Title-case).
_STREET_ABBR = {
    "street": "St", "avenue": "Ave", "road": "Rd", "drive": "Dr",
    "boulevard": "Blvd", "lane": "Ln", "court": "Ct", "place": "Pl",
    "circle": "Cir", "terrace": "Ter", "parkway": "Pkwy", "highway": "Hwy",
    "square": "Sq", "trail": "Trl",
}

# Compass directionals -> uppercase abbreviation (North -> N). DISTINCT
# directions stay distinct; this only standardizes formatting.
_DIR_ABBR = {
    "north": "N", "south": "S", "east": "E", "west": "W",
    "northeast": "NE", "northwest": "NW", "southeast": "SE", "southwest": "SW",
}

# Unit / secondary-designator markers standardized but KEPT (never dropped, per
# the display rule: "Suite D13" -> "Ste D13", "#D13" stays "#D13").
_UNIT_STD = {
    "suite": "Ste", "ste": "Ste", "apartment": "Apt", "apt": "Apt",
    "unit": "Unit", "floor": "Fl", "fl": "Fl", "building": "Bldg",
    "bldg": "Bldg", "room": "Rm", "rm": "Rm", "department": "Dept",
    "dept": "Dept",
}

# Organization initialisms that must stay ALL-CAPS when title-casing a name or
# address ("LLC", not "Llc"). Word-style suffixes (Inc, Corp, ...) are handled by
# _SUFFIX_TITLE below instead.
_KEEP_UPPER = frozenset({
    "LLC", "LLP", "PLLC", "PC", "PA", "LP", "USA", "US", "PO",
    "NE", "NW", "SE", "SW", "N", "S", "E", "W",
})

# Word-style entity suffixes -> canonical Title-case display form.
_SUFFIX_TITLE = {
    "inc": "Inc", "corp": "Corp", "co": "Co", "ltd": "Ltd",
    "incorporated": "Incorporated", "corporation": "Corporation",
    "company": "Company", "limited": "Limited",
}

# Entity-type value -> canonical display form (Beta Report Sec 5.2 synonym set).
_ENTITY_DISPLAY = {
    "llc": "Limited Liability Company",
    "limited liability company": "Limited Liability Company",
    "pllc": "Professional Limited Liability Company",
    "llp": "Limited Liability Partnership",
    "limited liability partnership": "Limited Liability Partnership",
    "lp": "Limited Partnership",
    "limited partnership": "Limited Partnership",
    "inc": "Incorporated",
    "incorporated": "Incorporated",
    "corp": "Corporation",
    "corporation": "Corporation",
    "co": "Company",
    "company": "Company",
    "ltd": "Limited",
    "limited": "Limited",
    "pc": "Professional Corporation",
    "professional corporation": "Professional Corporation",
}

# US state full name -> 2-letter uppercase abbreviation (Colorado -> CO).
_STATE_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN",
    "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}

_2LETTER_STATES = frozenset(_STATE_ABBR.values())

# Full state-name phrases, longest first, so "West Virginia" is matched before
# "Virginia" during the address state pass.
_STATE_PHRASES_SORTED = sorted(_STATE_ABBR.items(), key=lambda kv: len(kv[0]), reverse=True)

# A state (full name or 2-letter code) is only rewritten inside an address when
# it sits immediately before a 5-digit ZIP / ZIP+4 - the "state position". This
# keeps a street named "Virginia Ave" or "123 Or Ln" from being turned into a
# state abbreviation.
_ZIP_LOOKAHEAD = r"(?=[\s,]*\d{5}(?:-\d{4})?\b)"

_DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d",
    "%m/%d/%Y", "%m/%d/%y",
    "%m-%d-%Y", "%m-%d-%y",
    "%m.%d.%Y", "%m.%d.%y",
    "%B %d %Y", "%b %d %Y",
    "%d %B %Y", "%d %b %Y",
)


# ── Small helpers ─────────────────────────────────────────────────────────────

def _s(value: Any) -> str:
    """Whitespace-trimmed string form of a scalar value."""
    return "" if value is None else str(value).strip()


def _title_core(word: str, *, allow_suffix: bool = True) -> str:
    """Title-case a single alphabetic core word, PRESERVING content.

    - Known initialisms (LLC, LLP, ...) stay uppercase.
    - Known word suffixes (Inc, Corp, Co, ...) map to their canonical form -
      but only when ``allow_suffix`` (name context). In an ADDRESS "Co"/"Ltd"
      are not entity suffixes, so the caller passes allow_suffix=False.
    - An all-UPPER or all-lower token is title-cased (ORBIN -> Orbin).
    - A token that already carries internal capitals (McDonald, O'Brien-style
      once split) is LEFT UNTOUCHED so real mixed-case names are never mangled.
    """
    if not word:
        return word
    up = word.upper()
    if up in _KEEP_UPPER:
        return up
    low = word.lower()
    if allow_suffix and low in _SUFFIX_TITLE:
        return _SUFFIX_TITLE[low]
    if word.isupper() or word.islower():
        return word[:1].upper() + word[1:].lower()
    return word  # already mixed-case -> leave as-is


def _split_affix(token: str):
    """Split a whitespace token into (leading punct, core, trailing punct).

    Keeps punctuation like a trailing comma or a leading '#' so it can be
    re-attached after the core is transformed ("contracting," -> "Contracting,",
    "#d13" -> "#D13").
    """
    m = re.match(r"^(\W*)(.*?)(\W*)$", token, flags=re.DOTALL)
    if not m:
        return "", token, ""
    return m.group(1), m.group(2), m.group(3)


def _map_word(core: str, *, street: bool) -> str:
    """Standardize one address/name core word. ``street`` enables street-suffix,
    directional and unit standardization; otherwise only name-style title-casing.
    """
    low = core.lower()
    if street:
        if low in _STREET_ABBR:
            return _STREET_ABBR[low]
        if low in _DIR_ABBR:
            return _DIR_ABBR[low]
        if low in _UNIT_STD:
            return _UNIT_STD[low]
        # A state code already uppercased by the state pass (see _canon_phrase)
        # is left intact - never re-title-cased into "Co"/"In"/etc.
        if core.isupper() and core.upper() in _2LETTER_STATES:
            return core.upper()
        return _title_core(core, allow_suffix=False)
    return _title_core(core, allow_suffix=True)


def _canon_phrase(value: Any, *, street: bool) -> str:
    """Token-by-token standardization of a multi-word phrase (name or address)."""
    s = _s(value)
    if not s:
        return s
    if street:
        # State pass (address only): convert a state to its 2-letter uppercase
        # code, but ONLY in the state position (immediately before a ZIP), so a
        # street name that happens to be a state word is never rewritten.
        for _phrase, _ab in _STATE_PHRASES_SORTED:
            s = re.sub(rf"\b{re.escape(_phrase)}\b{_ZIP_LOOKAHEAD}", _ab, s, flags=re.IGNORECASE)
        s = re.sub(
            rf"\b([A-Za-z]{{2}})\b{_ZIP_LOOKAHEAD}",
            lambda m: m.group(1).upper() if m.group(1).upper() in _2LETTER_STATES else m.group(1),
            s,
        )
    # Collapse internal runs of whitespace but keep single spaces.
    out = []
    for token in re.split(r"\s+", s):
        lead, core, trail = _split_affix(token)
        if core:
            core = _map_word(core, street=street)
        out.append(f"{lead}{core}{trail}")
    result = " ".join(out)
    # Tidy comma spacing: "Denver ,CO" -> "Denver, CO"; "a ,b" -> "a, b".
    result = re.sub(r"\s+,", ",", result)
    result = re.sub(r",(?=\S)", ", ", result)
    return re.sub(r"\s+", " ", result).strip()


# ── Public canonicalizers (one per value type) ────────────────────────────────

def canonicalize_date(value: Any) -> str:
    """Return a date as MM/DD/YYYY. Unparseable input is returned unchanged."""
    s = _s(value)
    if not s:
        return s
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", s, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned.replace(",", " ")).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).strftime("%m/%d/%Y")
        except ValueError:
            continue
    return s


def canonicalize_currency(value: Any) -> str:
    """Return a money amount as $X,XXX[.CC]. Non-numeric input returned unchanged."""
    s = _s(value)
    if not s:
        return s
    cleaned = re.sub(r"[^\d.]", "", s)
    if cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")
    if not cleaned or cleaned == ".":
        return s
    try:
        dec = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return s
    if dec == dec.to_integral_value():
        return "${:,}".format(int(dec))
    return "${:,.2f}".format(dec)


def canonicalize_state(value: Any) -> str:
    """Return a US state as its 2-letter uppercase code. Unknown input unchanged."""
    s = _s(value)
    if not s:
        return s
    low = s.lower()
    if low in _STATE_ABBR:
        return _STATE_ABBR[low]
    if len(s) == 2 and s.upper() in _2LETTER_STATES:
        return s.upper()
    return s


def canonicalize_city(value: Any) -> str:
    """Title-case a city name, preserving mixed-case tokens."""
    return _canon_phrase(value, street=False)


def canonicalize_name(value: Any) -> str:
    """Standardize an organization/person name: fix casing, keep the entity
    suffix (LLC/Inc/...), tidy comma spacing. Content is never dropped."""
    return _canon_phrase(value, street=False)


def canonicalize_address(value: Any) -> str:
    """Standardize a street address line: abbreviate street suffixes and
    directionals, standardize (but keep) unit markers, uppercase a trailing
    state, fix casing. ZIP/ZIP+4 and unit numbers are preserved as-is."""
    return _canon_phrase(value, street=True)


def canonicalize_entity_type(value: Any) -> str:
    """Map an entity-type value to its canonical display form. Unknown unchanged."""
    s = _s(value)
    if not s:
        return s
    key = re.sub(r"[^a-z ]+", " ", s.lower())
    key = re.sub(r"\s+", " ", key).strip()
    return _ENTITY_DISPLAY.get(key, s)


# ── Field-name category inference + dispatcher ────────────────────────────────

def category_for_field(field_name: str) -> Optional[str]:
    """Infer the value type of an ACORD field from its NAME shape.

    Returns one of {"date","currency","state","city","address","name",
    "entity"} or None (leave the value untouched). Order matters: the more
    specific address sub-fields (postal / state / city) are resolved before the
    generic address / name checks so a "...MailingAddress_CityName_A" is treated
    as a city, not an address or a name.
    """
    if not field_name:
        return None
    fl = field_name.lower()
    # Postal codes and numeric identifiers are left exactly as extracted.
    if "postalcode" in fl or "zipcode" in fl or "postalcodeextension" in fl:
        return None
    if "stateorprovince" in fl or "state_code" in fl or fl.endswith("statecode"):
        return "state"
    if "cityname" in fl or fl.endswith("_city") or fl.endswith("cityname"):
        return "city"
    if "date" in fl:
        return "date"
    if "address" in fl and "line" in fl:
        return "address"
    if any(k in fl for k in ("amount", "revenue", "grosssales", "sales",
                             "payroll", "receipts")):
        return "currency"
    if "entitytype" in fl or ("legalentity" in fl and "description" in fl):
        return "entity"
    if "name" in fl:
        return "name"
    return None


_DISPATCH = {
    "date": canonicalize_date,
    "currency": canonicalize_currency,
    "state": canonicalize_state,
    "city": canonicalize_city,
    "address": canonicalize_address,
    "name": canonicalize_name,
    "entity": canonicalize_entity_type,
}


def canonicalize_for_field(field_name: str, value: Any) -> Any:
    """Return the clean display value for ``value`` given its ACORD field name.

    Returns the value UNCHANGED (same object) when there is nothing to do: empty
    value, a Yes/No checkbox answer, or a field whose type cannot be inferred.
    Never raises for ordinary input - the per-type canonicalizers are defensive.
    """
    if value is None:
        return value
    raw = str(value)
    if raw.strip() == "" or raw.strip() in ("Yes", "No", "null", "None"):
        return value
    category = category_for_field(field_name)
    if not category:
        return value
    fn = _DISPATCH.get(category)
    if not fn:
        return value
    return fn(value)
