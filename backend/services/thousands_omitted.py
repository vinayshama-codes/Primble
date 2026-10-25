"""A schedule printed in THOUSANDS (Z41, 25 Oct 2026, live f575160b).

The Excess policy's controlling-underlying endorsement heads its schedule
"POLICY LIMITS (000 OMITTED)" and prints the Amerisure umbrella as
"5,000 EACH OCCURRENCE" - $5,000,000. Read bare, every consumer took it for
$5,000. A schedule row's amount is scaled when the document it came from heads
a schedule "(000 omitted)" / "(000's omitted)" / "in thousands" and prints that
very amount, without a dollar sign, below the heading. An amount carrying "$"
or already in the hundreds of thousands is never scaled. Generic over the
list facts named in `SCHEDULE_FACTS`; a no-op on every other package.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, List

SCHEDULE_FACTS = ("underlying_policies",)
_HEADER_RE = re.compile(r"\(\s*0{3}'?s?\s+omitted\s*\)|\b0{3}'?s?\s+omitted\b|\bin\s+thousands\b", re.I)
_WINDOW = 2500
_AMOUNT_RE = re.compile(r"(?<![\d$,.])(\d{1,3}(?:,\d{3})?|\d{1,5})(?![\d,]*\d)(?!\s*%)")


def _thousands_windows(texts: Iterable[str]) -> List[str]:
    out = []
    for text in texts:
        for m in _HEADER_RE.finditer(text or ""):
            out.append(text[m.end(): m.end() + _WINDOW])
    return out


def _printed_bare(amount: str, windows: List[str]) -> bool:
    pat = re.compile(rf"(?<![\d$,.]){re.escape(amount)}(?![\d,])")
    return any(pat.search(w) for w in windows)


def scale_amount_text(text: str, windows: List[str], in_full: frozenset = frozenset()) -> str:
    """Each bare amount under 100,000 printed in a thousands-omitted window
    becomes its full dollar figure ("5,000 EACH OCCURRENCE" ->
    "$5,000,000 EACH OCCURRENCE"). An amount in `in_full` (a document's own
    schedule row states it in dollars) is never scaled."""
    if not windows or not isinstance(text, str) or "$" in text:
        return text

    def _one(m: "re.Match[str]") -> str:
        raw = m.group(1)
        num = int(raw.replace(",", ""))
        if num <= 0 or num >= 100_000 or num in in_full or not _printed_bare(raw, windows):
            return raw
        return f"${num * 1000:,}"

    return _AMOUNT_RE.sub(_one, text)


def scale_thousands_omitted(facts: dict, docs: Any) -> List[str]:
    """In place on the merged facts - and on each document's own facts, judged
    on that document's text alone; returns the merged facts changed. Never raises."""
    # The merged rows name no source document, so the merged pass reads every
    # document's headings - and must not scale an amount ANOTHER document's own
    # row states in full dollars (Z42 review C: "5,000" medical expense on one
    # dec, "5,000 EACH OCCURRENCE" under "(000 OMITTED)" on another).
    in_full: set = set()
    for d in (docs or []):
        if isinstance(d, dict) and isinstance(d.get("facts"), dict):
            in_full |= _amounts_in_full(d["facts"], _thousands_windows([str(d.get("text") or "")]))
    for d in (docs or []):
        if isinstance(d, dict) and isinstance(d.get("facts"), dict) and d.get("text"):
            _scale(d["facts"], _thousands_windows([str(d.get("text") or "")]))
    changed: List[str] = []
    try:
        texts = [str(d.get("text") or "") for d in (docs or []) if isinstance(d, dict)]
        changed = _scale(facts, _thousands_windows(texts), frozenset(in_full))
    except Exception:                                         # noqa: BLE001
        return changed
    return changed


def _schedule_texts(facts: dict):
    for key in SCHEDULE_FACTS:
        held = facts.get(key) if isinstance(facts, dict) else None
        rows = held.get("value") if isinstance(held, dict) and "value" in held else held
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict):
                for col in ("limit", "limits"):
                    if isinstance(row.get(col), str):
                        yield row[col]


def _amounts_in_full(facts: dict, windows: List[str]) -> set:
    """The bare amounts a document's own schedule rows state that its own
    thousands-omitted windows do not cover - dollars as printed."""
    out: set = set()
    try:
        for text in _schedule_texts(facts):
            if "$" in text:
                continue
            for m in _AMOUNT_RE.finditer(text):
                raw = m.group(1)
                if not (windows and _printed_bare(raw, windows)):
                    out.add(int(raw.replace(",", "")))
    except Exception:                                         # noqa: BLE001
        return out
    return out


def _scale(facts: dict, windows: List[str], in_full: frozenset = frozenset()) -> List[str]:
    changed: List[str] = []
    try:
        if not windows or not isinstance(facts, dict):
            return changed
        for key in SCHEDULE_FACTS:
            held = facts.get(key)
            rows = held.get("value") if isinstance(held, dict) and "value" in held else held
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                for col in ("limit", "limits"):
                    val = row.get(col)
                    new = scale_amount_text(val, windows, in_full) if isinstance(val, str) else val
                    if new != val:
                        row[col] = new
                        if key not in changed:
                            changed.append(key)
    except Exception:                                         # noqa: BLE001
        return changed
    return changed
