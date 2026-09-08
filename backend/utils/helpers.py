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
    if result.get("state") and result.get("zip"):
        _expected = _state_from_zip(result["zip"])
        if _expected and _expected != result["state"].upper():
            result["state"] = _expected
    return result