import os
import re
import secrets
from datetime import datetime, timezone
from typing import Optional


def safe_join(base: str, name: str) -> str:
    """Join base + name and raise ValueError if the result escapes base."""
    resolved = os.path.realpath(os.path.join(base, name))
    base_real = os.path.realpath(base)
    if not (resolved == base_real or resolved.startswith(base_real + os.sep)):
        raise ValueError(f"Unsafe path: '{name}' escapes base directory")
    return resolved


def generate_verification_code() -> str:
    # 6-digit code: randbelow(900000) gives 0-899999, +100000 gives 100000-999999
    return str(secrets.randbelow(900000) + 100000)


def _safe_parse_dt(raw) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw
    if isinstance(raw, str):
        normalized = raw.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def check_payment_access(payment_status: str, action: str = "form") -> None:
    """
    Raise HTTPException if the user's payment lifecycle status blocks the requested action.
    action='upload'  — blocked by soft_locked, suspended, archived
    action='form'    — blocked by suspended, archived (soft_locked can still access existing content)
    """
    from fastapi import HTTPException
    ps = (payment_status or "ok").lower()
    if ps == "archived":
        raise HTTPException(403, "Account archived due to non-payment. Contact support@primble.ai to reactivate.")
    if ps == "suspended":
        raise HTTPException(403, "Account suspended due to non-payment. Please update your billing to restore access.")
    if ps == "soft_locked" and action == "upload":
        raise HTTPException(403, "Account restricted due to non-payment. You can still view and download existing forms, but cannot upload or create new content until billing is resolved.")


# Each entry: (zip3_low, zip3_high, state_code).
# zip3 = first three digits of a 5-digit US ZIP as an integer (e.g. "80127" → 801).
# Used to validate/correct the state component of a parsed address when the
# LLM has confused states — most commonly when the document contains addresses
# in multiple states and the LLM picks the wrong one (e.g. CO vs MO).
_ZIP3_RANGES = [
    # New England
    ( 10,  27, "MA"), ( 28,  29, "RI"), ( 30,  38, "NH"),
    ( 39,  49, "ME"), ( 50,  59, "VT"), ( 60,  69, "CT"),
    ( 70,  89, "NJ"),
    # Mid-Atlantic
    (100, 149, "NY"), (150, 196, "PA"), (197, 199, "DE"),
    # DC / South Atlantic
    (200, 205, "DC"), (206, 219, "MD"), (220, 246, "VA"),
    (247, 268, "WV"), (270, 289, "NC"), (290, 299, "SC"),
    # Southeast
    (300, 319, "GA"), (320, 349, "FL"), (350, 369, "AL"),
    (370, 385, "TN"), (386, 397, "MS"), (398, 399, "GA"),
    # Mid-South / Great Lakes
    (400, 429, "KY"), (430, 459, "OH"), (460, 479, "IN"), (480, 499, "MI"),
    # Midwest
    (500, 528, "IA"), (530, 549, "WI"), (550, 567, "MN"),
    (570, 577, "SD"), (580, 588, "ND"), (590, 599, "MT"),
    # IL / MO / KS / NE
    (600, 629, "IL"), (630, 658, "MO"), (660, 679, "KS"), (680, 693, "NE"),
    # South Central
    (700, 714, "LA"), (716, 729, "AR"), (730, 749, "OK"), (750, 799, "TX"),
    # Mountain West
    (800, 816, "CO"), (820, 831, "WY"), (832, 838, "ID"), (840, 847, "UT"),
    (850, 865, "AZ"), (870, 884, "NM"), (889, 898, "NV"),
    # West Coast / Pacific
    (900, 961, "CA"), (967, 968, "HI"), (970, 979, "OR"),
    (980, 994, "WA"), (995, 999, "AK"),
]


_US_ZIP_STATES = frozenset(_st for _lo, _hi, _st in _ZIP3_RANGES)


def _state_from_zip(zip_str: str) -> Optional[str]:
    """Return the expected 2-letter US state code for a ZIP code, or None if unknown."""
    if not zip_str:
        return None
    digits = "".join(c for c in str(zip_str) if c.isdigit())
    if len(digits) < 3:
        return None
    z3 = int(digits[:3])
    for lo, hi, state in _ZIP3_RANGES:
        if z3 < lo:
            break
        if lo <= z3 <= hi:
            return state
    return None


# Comma-free tail shapes _parse_address recovers (see its tail-recovery block).
_ADDR_STATE_ZIP_TAIL_RE = re.compile(
    r"[\s,]+([A-Za-z]{2})\.?[\s,]+(\d{5}(?:-\d{4})?)\s*$")
_ADDR_UNIT_THEN_CITY_RE = re.compile(
    r"^(?P<street>.*?(?:#|\b(?:apt|suite|ste|unit|bldg|building|fl|floor"
    r"|rm|room)\b\.?)\s*[\w-]+)[\s,]+(?P<city>[A-Za-z][A-Za-z .'-]{2,})$",
    re.I,
)
# The same designators, but the WHOLE string is the unit and nothing else -
# "Suite 300", "# D13", "Ste 400". Used to tell a unit glued to a city from a
# street glued to a city; only the former may be split off. See recovery 4.
_ADDR_UNIT_ONLY_RE = re.compile(
    r"^(?:#|\b(?:apt|suite|ste|unit|bldg|building|fl|floor|rm|room)\b\.?)"
    r"\s*[\w-]+$", re.I,
)

# ── Comma-free addresses with NO unit designator (2026-09-01) ────────────────
# `_ADDR_UNIT_THEN_CITY_RE` above needs a unit ("Ste 400", "# D13") to find the
# street/city boundary. A great many premises have none, and for those the city
# was silently lost: the live T1 run parsed
#
#     "15 Foothills Service Rd Golden CO 80401"
#         -> line1 "15 Foothills Service Rd Golden", city None
#
# and ACORD 125 printed the street box with the city inside it and the CITY box
# empty. The second anchor is the street-suffix token, which is what actually
# ends a US street line.
#
# GREEDY BY CONSTRUCTION - `.*` before the suffix, so the LAST suffix wins. A
# non-greedy first draft took "Frontage" out of "2201 S Yuma Frontage Rd Pueblo"
# and "Ave" out of "77 Park Ave Court Denver", producing "Rd Pueblo" and
# "Court Denver" as cities. It failed four of the eight real addresses in the
# fixture before the greedy form was adopted.
#
# A LEADING HOUSE NUMBER IS REQUIRED, so "PO Box 4417 Cheyenne" and any bare
# name are left exactly as they are - the same positive-evidence rule the rest
# of this function follows. No number, no split, no guess.
_ADDR_STREET_SUFFIX = (
    r"(?:st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|way|ct|"
    r"court|cir|circle|pl|place|pkwy|parkway|ter|terrace|trl|trail|hwy|highway|"
    r"crossing|loop|run|row|walk|path|plaza|square|sq)"
)
_ADDR_SUFFIX_THEN_CITY_RE = re.compile(
    rf"^(?P<street>\d.*\b{_ADDR_STREET_SUFFIX}\b\.?)\s+"
    rf"(?P<city>[A-Za-z][A-Za-z .'-]{{2,}})$",
    re.I,
)

# The trailing unit designator, so it can be lifted out of line 1 into line 2.
# Only ever applied when comma-splitting produced no line2 of its own.
_ADDR_TRAILING_UNIT_RE = re.compile(
    r"^(?P<street>\d.*?)\s+(?P<unit>(?:#|\b(?:apt|suite|ste|unit|bldg|building"
    r"|fl|floor|rm|room|dept|lot)\b\.?)\s*[\w-]+)$",
    re.I,
)


def _is_us_state_word(value) -> bool:
    """A US state code ("CO", any case) or a full state name ("Colorado")."""
    text = str(value or "").strip().strip(".,")
    if text.upper() in _US_ZIP_STATES:
        return True
    from services.display_canonicalizer import _STATE_ABBR   # stdlib-only module, no cycle
    return text.lower() in _STATE_ABBR


_BARE_ZIP_PART_RE = re.compile(r"^\d{5}(?:-\d{4})?$")
_HOUSE_NUMBER_PART_RE = re.compile(r"^\d{1,6}[A-Za-z]?$")
_US_COUNTRY_PART_RE = re.compile(
    r"^(?:u\.?\s?s(?:\.?\s?a)?|united\s+states(?:\s+of\s+america)?)$", re.I)
_OTHER_COUNTRY_PART_RE = re.compile(r"^(?:canada|india|mexico)$", re.I)
_ENDS_IN_POSTAL_CODE_RE = re.compile(r"(?:\d{4,}(?:-\d{3,4})?|[A-Z]\d[A-Z]\s?\d[A-Z]\d)\s*$", re.I)
# "... TX 75201 USA" - the country glued after the ZIP, no comma.
_TRAILING_US_COUNTRY_RE = re.compile(
    r"(?<=\d)\s+(?:u\.?\s?s\.?\s?a\.?|united\s+states(?:\s+of\s+america)?)\s*$", re.I)


# ── A NON-US ADDRESS WHOSE COUNTRY IS PRINTED (Z41, 25 Oct 2026) ─────────────
# The account address "C-52, Astrea It services, sector 65, Noida, India,
# 201301" parsed as city "India", state "201301": the country-strip below only
# knew a country printed LAST, after a postal code, and the US reader then took
# the last two parts as city and "ST ZIP". A printed country is positive
# evidence the address is not American, so it is read by its own rule: the
# postal code is the PIN / postcode standing alone beside the country (or
# glued to it), the city is the part before them, and the state is filled only
# from a real province code (Canada) - never from a postal code or a country.
# A region printed WITH the postal code ("New Delhi, Delhi 110001, India") is
# left to the reader below, which already reads it as city + region.
_FOREIGN_COUNTRY_RE = re.compile(
    r"^(?:canada|india|mexico|united\s+kingdom|u\.?k\.?|great\s+britain|england|"
    r"scotland|wales|northern\s+ireland|ireland|australia|new\s+zealand|singapore|"
    r"philippines|south\s+africa|united\s+arab\s+emirates|u\.?a\.?e\.?|germany|"
    r"france)$", re.I)
_FOREIGN_POSTAL_RE = re.compile(
    r"^(?:\d{6}|\d{3}\s\d{3}|\d{4,5}|[A-Z]\d[A-Z]\s?\d[A-Z]\d"
    r"|[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})$", re.I)
_CA_PROVINCE_CODES = frozenset({"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU",
                                "ON", "PE", "QC", "SK", "YT"})
# "ON M5H 1A1" / "London SW1A 1AA": words, then an alphanumeric postcode.
_WORDS_THEN_ALNUM_POSTAL_RE = re.compile(
    r"^(?P<words>.*?)\s*(?P<pc>[A-Z]\d[A-Z]\s?\d[A-Z]\d|[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})$",
    re.I)


_CITY_THEN_PIN_RE = r"^(?P<city>[A-Za-z][A-Za-z .'-]*?)\s+(?P<pc>\d{6}|\d{3}\s\d{3}|\d{4,5})$"


def _parse_foreign_address(parts: list) -> Optional[dict]:
    """Read a comma-split address that PRINTS a non-US country, or None when
    it does not (or the shape is the region-with-postal one the US reader
    already handles)."""
    if len(parts) < 2:
        return None
    last, prev = parts[-1].strip(" ."), parts[-2].strip(" .")
    postal = region = None
    if _FOREIGN_COUNTRY_RE.match(prev) and _FOREIGN_POSTAL_RE.match(last):
        country, postal, rest = prev, last, parts[:-2]           # "..., India, 201301"
    elif _FOREIGN_COUNTRY_RE.match(last):
        country, rest = last, parts[:-1]
        if rest and _FOREIGN_POSTAL_RE.match(rest[-1].strip(" .")):
            postal, rest = rest[-1].strip(" ."), rest[:-1]        # "..., Noida, 201301, India"
        elif rest and _WORDS_THEN_ALNUM_POSTAL_RE.match(rest[-1].strip(" .")):
            m = _WORDS_THEN_ALNUM_POSTAL_RE.match(rest[-1].strip(" ."))
            postal, words = m.group("pc").upper(), m.group("words").strip(" ,")
            rest = rest[:-1]
            if words.upper() in _CA_PROVINCE_CODES and country.lower() == "canada":
                region = words.upper()                            # "Toronto, ON M5H 1A1, Canada"
            elif words:
                rest = rest + [words]                             # "London SW1A 1AA, UK"
        elif (len(rest) >= 2 and not re.search(r"\d", rest[-1])
              and rest[-1].split()[-1].upper() not in _US_ZIP_STATES):
            pass                                                  # "..., Monterrey, Mexico" - no postal
        elif len(rest) == 1 and re.match(_CITY_THEN_PIN_RE, rest[0].strip(" .")):
            # "Noida 201301, India": a city and its postal code, no street.
            m = re.match(_CITY_THEN_PIN_RE, rest[0].strip(" ."))
            return {"city": m.group("city"), "zip": m.group("pc")}
        else:
            return None                                           # region + postal: the US reader
    else:
        m = re.match(r"^(?P<c>.+?)\s+(?P<pc>\S+(?:\s\S{3})?)$", last)
        if not (m and _FOREIGN_COUNTRY_RE.match(m.group("c").strip(" .,"))
                and _FOREIGN_POSTAL_RE.match(m.group("pc"))):
            return None
        country, postal, rest = m.group("c"), m.group("pc"), parts[:-1]  # "..., India 201301"
    rest = [r for r in rest if r]
    if not rest:
        # Only a postal code beside the country ("201301, India"): the code is
        # the ZIP, never a street line (Z42 review A).
        return {"zip": postal} if postal else None
    if len(rest) >= 3 and _HOUSE_NUMBER_PART_RE.match(rest[0]) and rest[1][:1].isalpha():
        rest[:2] = [f"{rest[0]} {rest[1]}"]
    out: dict = {"line1": rest[0]}
    if len(rest) >= 2:
        city = rest[-1]
        toks = city.split()
        if (country.lower() == "canada" and len(toks) >= 2
                and toks[-1].upper() in _CA_PROVINCE_CODES and not region):
            region, city = toks[-1].upper(), " ".join(toks[:-1])
        out["city"] = city
        if len(rest) > 2:
            out["line2"] = ", ".join(rest[1:-1])
    if region:
        out["state"] = region
    if postal:
        out["zip"] = postal
    return out


def _parse_address(addr: str) -> dict:
    # SHAPE FIRST (2026-09-06). This went straight to `addr.split(",")`, so a
    # fact that arrived as a bool, an int, a list or a dict raised
    # AttributeError - INSIDE form generation, where an exception does not
    # surface as a bug report but as a form that failed to produce. Found by
    # fuzzing the stamper with 5,000 malformed fact dicts: 315 of them crashed,
    # all on the same line, e.g. `mailing_address = True`.
    #
    # An envelope is unwrapped because merged facts routinely arrive as
    # `{"value": ..., "confidence": ...}`; anything else non-string is not an
    # address and returns the same empty result an empty string always has.
    if isinstance(addr, dict):
        addr = addr.get("value")
    if not isinstance(addr, str) or not addr:
        return {}
    parts  = [p.strip() for p in addr.split(",")]
    _foreign = _parse_foreign_address(parts)
    if _foreign is not None:
        return _foreign
    # A trailing COUNTRY is not the state (round 5, 7 Oct 2026). "1234 Elm
    # Street, Suite 500, Dallas, TX 75201, USA" parsed as city "TX 75201",
    # state "USA" and line two "Suite 500, Dallas"; the stored corpus printed
    # "TX 75201" in 114 CITY boxes. The country part goes before the parts are
    # read. A non-US country only after a postal code ("..., Delhi 110020,
    # India"), so a bare last part like "Mexico" is never taken from a city.
    while len(parts) >= 2 and (
            _US_COUNTRY_PART_RE.match(parts[-1].strip(" ."))
            or (_OTHER_COUNTRY_PART_RE.match(parts[-1].strip(" ."))
                and _ENDS_IN_POSTAL_CODE_RE.search(parts[-2]))):
        parts.pop()
    if parts:
        parts[-1] = _TRAILING_US_COUNTRY_RE.sub("", parts[-1]).strip()
    # A STATE AND ZIP TYPED AS TWO PARTS ("Denver, CO, 80216") are one part, and
    # a HOUSE NUMBER TYPED AS ITS OWN PART ("402, Dana Street, ...") belongs to
    # the street (owner, 14 Oct 2026: "402 , dana street , Dnver,CO, 20132" read
    # "CO" as the city and the ZIP as the state, and the check said "Address
    # missing valid US state" beside a typed CO). Each merge needs its exact
    # shape: a bare US ZIP after a bare US state code; a bare house number
    # before a part that starts with a word.
    if len(parts) >= 3 and _BARE_ZIP_PART_RE.match(parts[-1]) \
            and parts[-2].strip().upper() in _US_ZIP_STATES:
        parts[-2:] = [f"{parts[-2].strip()} {parts[-1].strip()}"]
    if len(parts) >= 3 and _HOUSE_NUMBER_PART_RE.match(parts[0]) and parts[1][:1].isalpha():
        parts[:2] = [f"{parts[0]} {parts[1]}"]
    result = {}
    if len(parts) >= 1:
        result["line1"] = parts[0]
    if len(parts) >= 3:
        # 3-part format: "Street, City, ST ZIP"
        # 4+-part format: "Street, Suite/Unit, City, ST ZIP" - the segment(s)
        # between the street and the city (e.g. "Suite 310") used to be silently
        # dropped (neither line1 nor city nor anywhere); they belong on line2.
        if len(parts) > 3:
            result["line2"] = ", ".join(parts[1:-2])
        last = parts[-1].strip().split()
        if len(last) >= 2:
            result["state"] = last[-2]
            result["zip"]   = last[-1]
        elif len(last) == 1:
            result["state"] = last[0]
        result["city"] = parts[-2]
    elif len(parts) == 2:
        # 2-part format: "Street, City ST ZIP"  ← standard US mailing address
        last = parts[-1].strip().split()
        if len(last) >= 3:
            # e.g. ["Littleton", "CO", "80127"]
            result["city"]  = " ".join(last[:-2])
            result["state"] = last[-2]
            result["zip"]   = last[-1]
        elif len(last) == 2:
            # e.g. ["CO", "80127"]  (city was part of line1)
            result["state"] = last[0]
            result["zip"]   = last[1]
        elif len(last) == 1:
            result["state"] = last[0]
    # A STATE THAT IS NOT A STATE (owner, 14 Oct 2026). With no state typed,
    # "402 Dana Street, Denver 80216" read "Denver" as the state, and
    # "Street, Denver, 80216" read the ZIP as the state. A value in the state
    # slot that is neither a US state code nor a full state name is given back:
    # a bare ZIP to the zip, words to the city (what stood in the city slot on
    # a 3+ part address moves to line 2). No state is invented.
    _st = result.get("state")
    if _st is not None and not _is_us_state_word(_st):
        _tail = parts[-1].split() if parts else []
        _words = [t for t in _tail if not _BARE_ZIP_PART_RE.match(t)]
        if _BARE_ZIP_PART_RE.match(str(_st)) and not result.get("zip"):
            result.pop("state", None)
            result["zip"] = str(_st)                          # "Street, Denver, 80216"
        elif (_tail and _BARE_ZIP_PART_RE.match(_tail[-1]) and _words and len(_words) <= 4
              and all(w.isalpha() for w in _words)
              and not (len(_words) == 1 and len(_words[0]) == 2)):
            # (a lone 2-letter code there is a foreign region / country code -
            # "Paris, FR 75001" - never a city)
            # Only a US address: the last part ends in a bare US ZIP and the rest
            # of it is plain words (never prose, never a non-US postal code).
            result.pop("state", None)
            if _is_us_state_word(" ".join(_words)):
                result["state"] = " ".join(_words)            # "New York 10001"
            elif _US_COUNTRY_PART_RE.match(" ".join(_words).strip(" .")):
                pass                                          # "Anytown, USA 12345": a country is no city
            else:
                if result.get("city") and len(parts) >= 3:
                    result["line2"] = ", ".join(x for x in (result.get("line2"), result["city"]) if x)
                result["city"] = " ".join(_words)             # "Denver 80216"
    # ── Comma-free tail recovery (2026-08-14) ────────────────────────────────
    # Dec pages routinely print the whole address as ONE comma-free run
    # ("4800 DAHLIA ST # D13 DENVER CO 80216-3121"), and comma-splitting then
    # leaves city/state/zip fused inside line1 - the live ACORD 125 printed the
    # street box with the zip inside it AND the zip box filled. Two recoveries,
    # both anchored on structure rather than guesses:
    #   1. STATE+ZIP tail: accepted only when the 2-letter token and the ZIP
    #      corroborate each other (_state_from_zip) - "AVE NW 20500" is not a
    #      state, and the DC zip proves it.
    #   2. CITY after the UNIT designator: a US street line ends at its unit
    #      ("# D13", "STE 400"); alphabetic text after the unit is the city
    #      ("...STE 400 ENGLEWOOD"). No unit anchor, no attempt - a street/city
    #      boundary without one is not decidable.
    line1 = str(result.get("line1") or "")
    if line1 and not result.get("zip"):
        tm = _ADDR_STATE_ZIP_TAIL_RE.search(line1)
        if tm and (_state_from_zip(tm.group(2)[:5]) or "").upper() == tm.group(1).upper():
            result.setdefault("state", tm.group(1).upper())
            result["zip"] = tm.group(2)
            line1 = line1[:tm.start()].strip(" ,")
            result["line1"] = line1
    if line1 and not result.get("city"):
        cm = _ADDR_UNIT_THEN_CITY_RE.match(line1)
        if cm and cm.group("street").strip():
            result["city"] = cm.group("city").strip()
            result["line1"] = cm.group("street").strip(" ,")
            line1 = result["line1"]
    #   4. A UNIT that arrived GLUED TO THE CITY (2026-09-06). Recovery 2 above
    #      only runs when the city is still unknown, and on this shape the comma
    #      split has already filled it - wrongly:
    #
    #        "2255 Shorebank Avenue, Suite 300 Tacoma, WA 98402"
    #            -> parts[-2] is the city -> city = "Suite 300 Tacoma"
    #
    #      and the ACORD 125 CITY box printed exactly that, live, twice. This is
    #      not a malformed address: every ACORD and letterhead prints the unit on
    #      the street line and the city on the NEXT line, and extraction joins
    #      those two lines with a single comma. Run 3 of the same kit happened to
    #      emit a second comma and parsed correctly, which is why this looked
    #      fixed for one run - it was luck, not a fix.
    #
    #      Splits ONLY when the leading chunk is a unit and nothing else, so a
    #      city is never cut at a street name. Same designators as recovery 2.
    city_val = str(result.get("city") or "")
    if city_val:
        um = _ADDR_UNIT_THEN_CITY_RE.match(city_val)
        if um and um.group("city").strip():
            unit = um.group("street").strip(" ,")
            if unit and _ADDR_UNIT_ONLY_RE.match(unit):
                result["city"] = um.group("city").strip()
                if not str(result.get("line2") or "").strip():
                    result["line2"] = unit
    #   3. CITY after the STREET SUFFIX, for the very common address that has
    #      no unit at all ("15 Foothills Service Rd Golden"). Runs only when
    #      rule 2 found nothing, so a unit-bearing address keeps its existing,
    #      proven behaviour untouched.
    if line1 and not result.get("city"):
        sm = _ADDR_SUFFIX_THEN_CITY_RE.match(line1)
        if sm and sm.group("street").strip():
            result["city"] = sm.group("city").strip()
            result["line1"] = sm.group("street").strip(" ,")
            line1 = result["line1"]
    #   4. The UNIT belongs on line 2, not buried at the end of line 1. ACORD
    #      prints them as separate boxes and the live run left every line-two
    #      box blank while the suite sat inside the street. Runs LAST, because
    #      rule 2 uses the unit as its city anchor - lifting it earlier would
    #      remove the anchor before it was used.
    #
    #      Never overwrites a line2 that comma-splitting already produced, and
    #      never empties line1 (the `\d.*?` street part must survive).
    if line1 and not (result.get("line2") or "").strip():
        um = _ADDR_TRAILING_UNIT_RE.match(line1)
        if um and um.group("street").strip():
            result["line1"] = um.group("street").strip(" ,")
            result["line2"] = um.group("unit").strip()
    # Validate/correct state against ZIP. The LLM occasionally extracts the
    # wrong state when the document contains multiple addresses from different
    # states (e.g. insured in CO, premises in MO). ZIP codes are unambiguous;
    # if they conflict with the parsed state, the ZIP wins.
    # Only a US ZIP against a US state, though: "UP 201301" (an Indian PIN in an
    # agency's address, 1 Oct 2026) read its first three digits as a DC prefix
    # and printed DC.
    if result.get("state") and result.get("zip"):
        _us_zip = re.fullmatch(r"\d{5}(?:-\d{4})?", str(result["zip"]).strip())
        _us_state = str(result["state"]).strip().upper() in _US_ZIP_STATES
        _expected = _state_from_zip(result["zip"]) if (_us_zip and _us_state) else None
        if _expected and _expected != result["state"].upper():
            result["state"] = _expected
    return result