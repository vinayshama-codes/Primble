"""Deterministic recovery of a JSON object cut off by an output-token cap.

SINGLE SOURCE OF TRUTH. This logic lived only inside `pdf_service`, where the
gap-fill stage learned (improving-ll.md) that re-sending a whole prompt after a
parse failure re-bills every input token to get the SAME truncation back at
temperature 0. The extraction stage never got that lesson and treated a parse
failure as fatal, so one truncated chunk reply aborted an entire upload with a
500 (live 2026-08-15, the client's 271-page package).

Both stages now call this one function. Two copies of a parser is how the two
drift, and a drift here is invisible until it eats a document.
"""

from __future__ import annotations

import json
from typing import List, Optional

__all__ = ["salvage_truncated_json"]


def salvage_truncated_json(text: str) -> Optional[dict]:
    """Best-effort recovery of a JSON object cut off mid-write.

    Rewinds to the last completed element and closes the open brackets: the
    content the model DID finish is perfectly good. String state and escape
    sequences are tracked so a brace or comma INSIDE a quoted value (an address
    "Suite 3, Building B", an ACORD tooltip) can never be mistaken for
    structure.

    Returns the salvaged dict, or None when nothing complete can be recovered.
    Never raises - a salvage attempt must not become a second failure mode.
    """
    try:
        s = (text or "").strip()
        start = s.find("{")
        if start == -1:
            return None
        s = s[start:]
        stack: List[str] = []
        in_str = esc = False
        # Every comma, with the bracket stack in force at that point. A comma
        # means "the element before me, at this depth, is finished".
        commas: List[tuple] = []
        for i, ch in enumerate(s):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                stack.append("}")
            elif ch == "[":
                stack.append("]")
            elif ch in "}]":
                if stack:
                    stack.pop()
            elif ch == "," and stack:
                commas.append((i, list(stack)))
        if not commas:
            return None

        # PREFER A CUT OUTSIDE THE CONTAINER THAT WAS STILL BEING WRITTEN.
        # `len(stack)` at end-of-text is how deep the truncation happened. A
        # comma at that same depth sits INSIDE the half-written element, so
        # cutting there closes it into something syntactically valid but
        # semantically partial - a dec entry with a label and no value, a
        # vehicle row with a VIN and no make. That is precisely the broken
        # half-relationship this product must not manufacture, so the deepest
        # incomplete element is dropped whole.
        #
        # Fallback to the last comma at any depth when there is no shallower
        # one: that is the gap-fill shape (`{"values": {"A": 1, "B": 2, "C`),
        # where the innermost container IS the payload and its finished
        # key/value pairs are exactly what we want to keep.
        depth_at_truncation = len(stack)
        shallower = [c for c in commas if len(c[1]) < depth_at_truncation]
        cut, cut_stack = (shallower or commas)[-1]

        candidate = s[:cut] + "".join(reversed(cut_stack))
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) and parsed else None
    except Exception:                                      # pragma: no cover
        return None
