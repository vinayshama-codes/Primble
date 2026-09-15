"""Boxes a form prints under an "APPLICABLE ONLY IN <STATE>" heading.

Live 15 Sep 2026 (and the 10 Sep run before it): ACORD 126 ticked "MEDICAL
PAYMENTS COVERAGE IS AVAILABLE" on a Colorado contractor. The form prints that
box under "APPLICABLE ONLY IN WISCONSIN: IF NON-OWNED ONLY AUTO COVERAGE IS TO BE
PROVIDED UNDER THE POLICY" - a question that does not exist for this risk, so any
answer is a guess, and the model answered it from the AUTO policy's med pay.

The schema cannot say this: the four boxes' tooltips name no state. The TEMPLATE
does, so it is read from the template, the same way `state_auto_grid` reads its
page headings - no hand-written list of boxes. A heading and the line printed
under it form the block; measured on all 17 templates, that captures exactly the
four ACORD 126 Wisconsin boxes and ACORD 131's Montana initials box, and nothing
else (Kansas on ACORD 127 and the other ACORD 131 headings print no box there).

Positive evidence only, both ways: the risk's states must be KNOWN and none of
them the block's state before a box is withheld. No state on file, an unreadable
template or a box outside every block means no opinion.
"""
from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from types import MappingProxyType
from typing import Any, FrozenSet, Mapping

logger = logging.getLogger(__name__)

# "APPLICABLE ONLY IN WISCONSIN: ..." / "APPLICABLE ONLY IN LOUISIANA, MONTANA,
# NEW HAMPSHIRE AND VERMONT" - the state list ends at a colon, a full stop or the
# end of the printed line.
_HEADING_RE = re.compile(r"\bAPPLICABLE\s+ONLY\s+IN\s+([A-Z][A-Z ,]*?)\s*(?=:|\.|$)")


def _state_codes(phrase: str) -> FrozenSet[str]:
    from services.form_service import _STATE_NAME_TO_CODE
    codes = set()
    for part in re.split(r",|\bAND\b", phrase.upper()):
        code = _STATE_NAME_TO_CODE.get(part.strip())
        if code:
            codes.add(code)
    return frozenset(codes)


@lru_cache(maxsize=32)
def restricted_boxes(form_id: str) -> Mapping[str, FrozenSet[str]]:
    """{field name: the states its block applies in}, read off the template."""
    try:
        import pdfplumber
        from config.settings import TEMPLATE_DIR
    except Exception:                                          # noqa: BLE001
        return MappingProxyType({})
    path = os.path.join(TEMPLATE_DIR, f"{form_id}.pdf")
    if not os.path.exists(path):
        return MappingProxyType({})
    out: dict = {}
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                lines: dict = {}
                for word in page.extract_words(use_text_flow=True):
                    lines.setdefault(round(word["top"]), []).append(word)
                tops = sorted(lines)
                for i, top in enumerate(tops):
                    text = " ".join(w["text"] for w in sorted(lines[top], key=lambda w: w["x0"]))
                    m = _HEADING_RE.search(text.upper())
                    if not m:
                        continue
                    states = _state_codes(m.group(1))
                    if not states:
                        continue
                    # The heading's own line and the one printed under it.
                    bottom = tops[i + 2] if i + 2 < len(tops) else top + 30
                    for annot in page.annots or []:
                        name = annot.get("title") or ""
                        if isinstance(name, bytes):
                            name = name.decode("latin-1", "ignore")
                        name = str(name).strip()
                        a_top = annot.get("top")
                        if name and a_top is not None and top - 2 <= a_top < bottom - 1:
                            out[name] = frozenset(out.get(name, frozenset()) | states)
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("state_restricted_boxes: cannot read the %s template: %s",
                       form_id, exc)
        return MappingProxyType({})
    return MappingProxyType(out)


def outside_its_state(form_id: str, field_name: str, facts: Any) -> bool:
    """True when this box belongs to a state block and the risk is provably
    elsewhere - every state we hold for it is outside the block's states."""
    states = restricted_boxes(str(form_id or "")).get(str(field_name or ""))
    if not states:
        return False
    from services.form_service import _collect_states
    risk = _collect_states(facts if isinstance(facts, dict) else {})
    return bool(risk) and not (risk & states)
