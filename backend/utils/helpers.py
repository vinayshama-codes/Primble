import os
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


def _parse_address(addr: str) -> dict:
    if not addr:
        return {}
    parts  = [p.strip() for p in addr.split(",")]
    result = {}
    if len(parts) >= 1:
        result["line1"] = parts[0]
    if len(parts) >= 3:
        # 3-part format: "Street, City, ST ZIP"
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
    # Validate/correct state against ZIP. The LLM occasionally extracts the
    # wrong state when the document contains multiple addresses from different
    # states (e.g. insured in CO, premises in MO). ZIP codes are unambiguous;
    # if they conflict with the parsed state, the ZIP wins.
    if result.get("state") and result.get("zip"):
        _expected = _state_from_zip(result["zip"])
        if _expected and _expected != result["state"].upper():
            result["state"] = _expected
    return result