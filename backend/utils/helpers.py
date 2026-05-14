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


def _parse_address(addr: str) -> dict:
    if not addr:
        return {}
    parts  = [p.strip() for p in addr.split(",")]
    result = {}
    if len(parts) >= 1:
        result["line1"] = parts[0]
    if len(parts) >= 3:
        last = parts[-1].strip().split()
        if len(last) >= 2:
            result["state"] = last[-2]
            result["zip"]   = last[-1]
        result["city"] = parts[-2]
    return result