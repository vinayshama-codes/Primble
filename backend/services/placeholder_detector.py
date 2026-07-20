"""placeholder_detector.py

Detects when a value stamped onto an ACORD form is a PLACEHOLDER rather than
real data extracted from a document - e.g. "1st distinct value", "<insert
value>", "Lorem ipsum". This is a different problem than
``pdf_service._is_empty_llm_value`` (which catches "the model said there is no
value") - a placeholder is worse: it's the model, or a malformed prompt
response, echoing INSTRUCTIONAL TEXT back as if it were a real answer. Left
unchecked, that text gets stamped onto a real ACORD form and shipped to a
carrier looking like a real (wrong) value.

Root cause this was written for: the repeating-group gap-fill prompt in
``pdf_service.py`` instructs the model to "assign 1st distinct value -> _A,
2nd -> _B" - and a confused model occasionally echoes that instruction text
back as the field's VALUE instead of finding the real data. This module is
the generic, form-agnostic backstop against that (and similar) failure modes,
independent of the prompt-wording fix applied at the source.

Design notes
------------
* PURE module - no DB, no I/O, no network. Easy to unit-test.
* CONSERVATIVE - only flags patterns that could never legitimately appear as
  real insurance-form data (an ordinal + "distinct value", a template bracket
  wrapping the whole value, a known filler word standing alone). It does NOT
  do generic heuristics like "repeated character" or "looks short" that could
  false-positive on legitimate short values (a single letter, a 2-digit code,
  a real dollar amount).
"""

import re
from typing import Any, Optional, Tuple

PLACEHOLDER_DETECTOR_MODEL_VERSION = "1.0.0"

_ORDINAL_WORDS = (
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
    "eighth", "ninth", "tenth", "eleventh", "twelfth",
)

# Matches "1st distinct value", "2nd distinct value(s)", "first distinct value", etc.
# - the exact instructional phrase from the repeating-group prompt in pdf_service.py.
_DISTINCT_VALUE_RE = re.compile(
    r"^\s*(?:\d+\s*(?:st|nd|rd|th)|" + "|".join(_ORDINAL_WORDS) + r")\s+distinct\s+value(?:s)?\s*$",
    re.IGNORECASE,
)

# The phrase "distinct value(s)" should never legitimately appear in real
# insurance-form data on its own - catches partial echoes ("up to 3 distinct
# values", "null if fewer distinct values exist") that don't match the exact
# ordinal pattern above but are still clearly leaked instruction text.
_DISTINCT_VALUE_FRAGMENT_RE = re.compile(r"distinct\s+values?", re.IGNORECASE)

# Other leaked-instruction fragments from the same repeating-group prompt.
_INSTRUCTION_LEAK_RE = re.compile(
    r"leave\s+(?:a\s+)?slot\s+null|null\s+if\s+fewer|never\s+copy\s+the\s+same\s+value|"
    r"assign\s+\d+\s*(?:st|nd|rd|th)\s|repeating\s+group",
    re.IGNORECASE,
)

# A value that is ENTIRELY a template placeholder wrapper: "<...>", "[...]",
# "{{...}}", "{...}". Real insurance data is never bracket-wrapped in full.
_TEMPLATE_BRACKET_RE = re.compile(r"^\s*(?:<[^<>]{1,120}>|\[[^\[\]]{1,120}\]|\{\{?[^{}]{1,120}\}?\})\s*$")

# Standalone filler words/phrases that are never a legitimate field value by
# themselves (case-insensitive, whole-value match only - a real value that
# merely CONTAINS one of these substrings, e.g. a business named "Sample
# Logistics LLC", is not flagged).
_FILLER_WHOLE_VALUE = frozenset({
    "lorem ipsum", "sample text", "example text", "example value",
    "placeholder", "placeholder text", "placeholder value",
    "insert value here", "insert value", "insert text here",
    "your text here", "todo", "tbd - todo", "xxx", "xxxx", "xxxxx",
    "fill in", "fill this in", "to be filled in", "to be filled",
})


def is_placeholder_value(value: Any) -> Tuple[bool, Optional[str]]:
    """Return (True, reason) if ``value`` looks like leaked instruction text
    or a template placeholder rather than real form data; (False, None)
    otherwise.

    ``reason`` is a short machine-stable code for logging/reporting:
      "ordinal_distinct_value" | "distinct_value_fragment" |
      "instruction_leak" | "template_bracket" | "filler_word"
    """
    if value is None:
        return False, None
    s = str(value).strip()
    if not s:
        return False, None

    if _DISTINCT_VALUE_RE.match(s):
        return True, "ordinal_distinct_value"
    if _DISTINCT_VALUE_FRAGMENT_RE.search(s):
        return True, "distinct_value_fragment"
    if _INSTRUCTION_LEAK_RE.search(s):
        return True, "instruction_leak"
    if _TEMPLATE_BRACKET_RE.match(s):
        return True, "template_bracket"
    if s.lower() in _FILLER_WHOLE_VALUE:
        return True, "filler_word"

    return False, None
