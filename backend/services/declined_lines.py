"""Which lines of business the submission says it is NOT requesting.

SYS-04's door (`line_presence`) asks "is this line part of the submission -
active OR INTENTIONALLY REQUESTED?". This module reads the submission's own
answer from the uploaded text: "NOT REQUESTED: workers compensation ...",
"LINES NOT REQUESTED" followed by a list, "Inland Marine: Not requested",
"Workers compensation stays with X and is not being marketed".

REBUILT 5 Oct 2026 after an adversarial audit of the first reader (which lived
in `extraction_service`). That reader:
  * read CH125's punctuation only. A heading with no colon - the layout of BOTH
    other decline-bearing kits in the database (FR125, Meridian) - read nothing;
  * matched a line WORD anywhere in a clause through `canon_line`'s substring
    test. So "Workers comp loss runs: not needed", "The garage at the rear is not
    part of this submission" and a premium-table row printed above an unrelated
    sentence all declined a line - 43 of 66 should-not-act probes.
A wrong decline is silent and destructive: it demotes the coverage flag, clears
the line's stops, hides its questions and drops its application form.

THE RULE NOW: a decline is read only where the words naming the line are
NOTHING BUT line names - "Workers Compensation and Inland Marine", "the umbrella
coverage", "Commercial Auto" - in one of a few statement shapes. "Workers comp
loss runs", "Smith Auto Body LLC", "Hired and Non-Owned Auto", "Excess liability
above $5M" and "the property at 12 Main St" never consume fully, so they never
decline anything. Precision first: a missed decline leaves the package exactly
as it was before the reader existed; a false one silently deletes a line.

The vocabulary is `lob_canon`'s own phrase tables (D9: no phrase is added here),
minus coverage PARTS and minus words that name a THING as often as a line, and
every family assignment is `lob_canon.canon_line`'s. Deterministic, no LLM.

Shapes read (each needs the full-consumption test):
  * a decline heading or label, with or without a colon, and the list after it -
    on its own line, across lines, or as checkbox / bullet rows;
  * "<line>: not requested" / "<line> - not needed" / "<line> | Not Requested";
  * "<line> is not requested / not being marketed / not part of this submission",
    including a coordinated predicate ("WC stays with X and is not marketed");
  * "we are not requesting / marketing <line>", "quote <line> separately",
    "quote all lines except <line>", "Excluding <line>, please quote ...".
Never: a question, a conditional ("if", "unless", "until"), a partial decline
("for the Ohio employees", "at Location 2"), past tense, a pronoun subject.
A line the same documents state as REQUESTED is contested and not recorded.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from services import lob_canon as _lc

# ── Vocabulary ───────────────────────────────────────────────────────────────

# lob_canon reads these as its families for COVERAGE ROWS; as a decline they
# name a PART of a line, never the line ("NOT REQUESTED: Products and Completed
# Operations" says nothing about General Liability as a whole).
_PART_PHRASES = frozenset({
    "premises operations", "premises liability", "products completed operations",
    "products liability", "completed operations", "business personal property", "bpp",
})
# Names a THING as often as a line - a line only with a coverage word or a
# "commercial" / "business" qualifier ("installation floater", "garage liability";
# never "the installation at the customer's home", "the garage").
_THING_PHRASES = frozenset({
    "vehicle", "garage", "building", "installation", "contractors equipment",
    "computer equipment",
})
# A line word that is also an everyday noun: never after a determiner without
# a coverage word ("Property: not requested" is the line; "the property" is a
# premises, "the auto" a vehicle).
_AMBIGUOUS_BARE = frozenset({"auto", "automobile", "property"})

_CONNECTORS = frozenset({"and", "or", ",", ";", "/", "|", "-", "plus"})
_DETERMINERS = frozenset({"the", "our", "their", "its", "his", "her", "your", "any",
                          "a", "an", "this", "these", "those", "each", "all"})
_QUALIFIERS = frozenset({"commercial", "business", "employee", "employees"})
_COVERAGE_WORDS = frozenset({"liability", "liab", "coverage", "coverages", "insurance",
                             "policy", "policies", "line", "lines", "floater", "floaters",
                             "form", "program", "programme"})


def _phrase_table() -> Tuple[Tuple[str, ...], ...]:
    rows: Set[Tuple[str, ...]] = set()
    for _fam, phrases in tuple(_lc._SPECIFIC) + tuple(_lc._SPECIALTY):
        for p in phrases:
            p = p.strip()
            if p and p not in _PART_PHRASES:
                rows.add(tuple(p.split()))
    for _fam, abbreviations in _lc._ABBREVIATIONS:
        rows.update((a,) for a in abbreviations)
    for p in _lc._GL_PHRASES:
        if p not in _PART_PHRASES:
            rows.add(tuple(p.split()))
    return tuple(sorted(rows, key=lambda r: (-len(r), r)))


_PHRASES = _phrase_table()

# ── Tokens ───────────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[A-Za-z]+|\d[\d,.]*|\S")


def _normalise(text: str) -> str:
    s = str(text or "").replace("’", "'").replace("‘", "'")
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)                 # WorkersCompensation
    s = re.sub(r"(?i)\b(\w+)'s\b", r"\1s", s)                  # worker's -> workers
    return s.replace("'", "")


def _tokens(text: str) -> List[str]:
    out: List[str] = []
    for m in _TOKEN_RE.finditer(_normalise(text)):
        t = m.group(0)
        if t[0].isalpha():
            out.append(t.lower())
        elif t[0].isdigit():
            out.append("#")                      # a number never names a line
        elif t == "&":
            out.append("and")
        elif t in "–—":
            out.append("-")
        else:
            out.append(t)                        # "$", ".", ":", "(" ... block
    return out


def _phrase_at(toks: Sequence[str], i: int) -> Optional[Tuple[str, ...]]:
    """The longest vocabulary phrase starting at `toks[i]` (a final plural
    "s" / "es" tolerated, as `canon_line`'s substring test does)."""
    for p in _PHRASES:
        k = len(p)
        if i + k > len(toks):
            continue
        if all(toks[i + j] == p[j] for j in range(k - 1)):
            last = toks[i + k - 1]
            if last == p[-1] or last in (p[-1] + "s", p[-1] + "es"):
                return p
    return None


def _segment_at(toks: Sequence[str], i: int) -> Optional[Tuple[str, int]]:
    """One line name starting at `toks[i]`: (family, index after it) or None.

    An optional determiner, an optional "commercial" / "business" qualifier,
    a vocabulary phrase, then any coverage words ("liability", "coverage",
    "floater")."""
    n = len(toks)
    start = i
    det = False
    while i < n and toks[i] in _DETERMINERS:
        det = True
        i += 1
    q = i
    while q < n and toks[q] in _QUALIFIERS:
        q += 1
    best: Optional[Tuple[int, int, Tuple[str, ...]]] = None
    for at in ((i, q) if q != i else (i,)):
        p = _phrase_at(toks, at)
        if p and (best is None or at + len(p) > best[1]):
            best = (at, at + len(p), p)
    if best is None:
        return None
    at, k, phrase = best
    cov = False
    while k < n and toks[k] in _COVERAGE_WORDS:
        cov = True
        k += 1
    qualified = at > i
    joined = " ".join(phrase)
    if joined in _THING_PHRASES and not (cov or qualified):
        return None
    if joined in _AMBIGUOUS_BARE and det and not (cov or qualified):
        return None
    fam = _lc.canon_line(" ".join(toks[start:k]))
    return (fam, k) if fam else None


def _consume(toks: Sequence[str]) -> Tuple[List[str], int, bool]:
    """(families named, index after the last whole line name, consumed all?)."""
    n = len(toks)
    i = 0
    last = 0
    fams: List[str] = []
    while i < n:
        if toks[i] in _CONNECTORS:
            i += 1
            continue
        seg = _segment_at(toks, i)
        if seg is None:
            return fams, last, False
        fam, i = seg
        last = i
        if fam not in fams:
            fams.append(fam)
    return fams, last, True


def families_of_tokens(toks: Sequence[str]) -> Optional[List[str]]:
    """The line families `toks` name, when they are NOTHING BUT line names.

    Line names joined by "and" / "," / "/" / "&", each optionally led by a
    determiner or a "commercial" / "business" qualifier and followed by
    coverage words ("liability", "coverage", "floater"). Anything else - a
    number, a part, a company, a document word - and the answer is None.
    """
    fams, _last, whole = _consume(list(toks))
    return fams if (whole and fams) else None


def line_name_families(text: str) -> Optional[List[str]]:
    """`families_of_tokens` over a string."""
    return families_of_tokens(_tokens(text))


def _leading_families(toks: Sequence[str]) -> Tuple[Optional[List[str]], int]:
    """The line names `toks` START with, and where they end."""
    fams, last, _whole = _consume(list(toks))
    return (fams, last) if fams else (None, 0)


# ── Text preparation ─────────────────────────────────────────────────────────

# A parenthetical is an aside - "(stays with TEM, policy TEM-WC-0558213)",
# "($5,000,000 each occurrence)". Bounded: no blank line inside, at most 400
# characters, so a stray OCR "(" can never swallow a page.
_PAREN_RE = re.compile(r"\((?:[^()\n]|\n(?![ \t]*\n)){0,400}\)")


def _strip_parentheticals(text: str) -> str:
    prev = None
    while prev != text:
        prev, text = text, _PAREN_RE.sub(" ", text)
    return text


# A list ends at a full stop - not one closing an initial or an abbreviation.
_ABBREVIATIONS = frozenset({"comp", "liab", "prop", "ins", "co", "inc", "corp", "dept",
                            "misc", "no", "st", "llc", "ltd", "wc", "gl", "im"})


def _sentence_end(s: str, start: int = 0) -> int:
    """Index of the first sentence-ending ". ", "!", "?" in `s` from `start`, or -1."""
    for m in re.finditer(r"[.!?](?=\s|$)", s[start:]):
        j = start + m.start()
        if s[j] in "!?":
            return j
        word = re.search(r"([A-Za-z]+)\s*$", s[:j])
        if word and (len(word.group(1)) == 1 or word.group(1).lower() in _ABBREVIATIONS):
            continue
        return j
    return -1


# ── Statuses, conditions and partial declines ────────────────────────────────

_STATUS = (r"not\s+(?:being\s+)?(?:requested|marketed|quoted)|not\s+(?:wanted|needed)"
           r"|declined\s+by\s+(?:the\s+)?(?:named\s+)?(?:insured|applicant|client|customer)"
           r"|(?:excluded|omitted|removed)\s+from\s+(?:this|the)\s+(?:submission|request|quote)")
_STATUS_RE = re.compile(r"(?i)^(?:" + _STATUS + r")\b")
# A trailing status on a list row: "Crime and Fidelity NO COVERAGE",
# "Workers Compensation Not covered under this programme", "... declined by the
# applicant". Read only where the row's head is already nothing but line names.
_ROW_STATUS_TAIL_RE = re.compile(
    r"(?i)\s+(?:-\s*)?(?:no|not|none|n/?a|declined|excluded|omitted|already|currently|"
    r"placed|written|insured|handled|carried|stays|remains|renews|monoline|separately|with)\b.*$")
_CONDITION_RE = re.compile(r"(?i)\b(?:if|unless|whether|until|once|provided\s+that|"
                           r"subject\s+to|pending|depending)\b")
_PARTIAL_RE = re.compile(r"(?i)^\s*(?:for|at|in|on|to|except|other\s+than|beyond|above|"
                         r"below|over|under|outside|within|with\s+respect\s+to|as\s+(?:respects|to))\b")
_TIME_TRAILER_RE = re.compile(
    r"(?i)^\s*(?:at\s+(?:this|the\s+present)\s+(?:time|renewal|stage|point)|at\s+present"
    r"|for\s+(?:this|the)\s+(?:renewal|term|year|policy\s+(?:term|period)|upcoming\s+(?:term|renewal))"
    r"|this\s+(?:renewal|term|year)|in\s+(?:this|the)\s+(?:submission|request|renewal|package|programme|program)"
    r"|on\s+this\s+(?:submission|renewal|account)|by\s+(?:the\s+)?(?:named\s+)?(?:insured|applicant|client)"
    r"|to\s+(?:other|any|additional|new|outside)\s+(?:carriers?|markets?|insurers?|companies))\b")
_TIME_TAIL_RE = re.compile(
    r"(?i)\s+(?:at\s+(?:this|the\s+present)\s+(?:time|renewal|stage|point)|at\s+present"
    r"|for\s+(?:this|the)\s+(?:renewal|term|year|upcoming\s+(?:term|renewal))"
    r"|this\s+(?:renewal|term|year)|currently|either|anymore|any\s+longer)\s*$")


def _clause_head(post: str) -> str:
    """`post` up to its first clause break."""
    m = re.search(r"[,;:]|\s-\s|\b(?:but|and|because|since|so)\b", post)
    return post[:m.start()] if m else post


def _partial(post: str) -> bool:
    head = _clause_head(post)
    return bool(_PARTIAL_RE.match(head)) and not _TIME_TRAILER_RE.match(head)


# ── Lists under a heading or label ───────────────────────────────────────────

_LIST_START = r"(?:^|(?<=;)|(?<=\|))[ \t]*(?:[-*•|]+[ \t]*)?"
_DECLINE_HEAD_RE = re.compile(
    r"(?im)" + _LIST_START +
    r"(?P<head>(?P<lines>(?:lines?|coverages?)(?:[ \t]+of[ \t]+business)?[ \t]+)?"
    r"(?:not[ \t]*(?:requested|being[ \t]+(?:requested|marketed|quoted)|marketed|wanted|needed)"
    r"|(?:excluded|omitted|removed)[ \t]+from[ \t]+(?:this|the)[ \t]+(?:request|submission|quote|marketing)"
    r"|declined[ \t]+by[ \t]+(?:the[ \t]+)?(?:named[ \t]+)?(?:insured|applicant|client|customer))"
    r"(?:[ \t]*/[ \t]*not[ \t]+in[ \t]+force)?)"
    r"[ \t]*(?P<sep>[:\-–|]|$)")
_REQUEST_HEAD_RE = re.compile(
    r"(?im)" + _LIST_START +
    r"(?P<head>(?P<lines>(?:lines?|coverages?)(?:[ \t]+of[ \t]+business)?[ \t]+)"
    r"(?:requested|being[ \t]+requested|to[ \t]+be[ \t]+quoted))"
    r"[ \t]*(?P<sep>[:\-–|]|$)")
_MARKER_RE = re.compile(
    r"^[ \t]*(?:(?P<box>\[[ \t]*(?P<tick>[xX✓✔*])?[ \t]*\]|\([ \t]*(?P<tick2>[xX])?[ \t]*\)"
    r"|(?P<ubox>[☐□])|(?P<tbox>[☑☒■]))"
    r"|(?P<bullet>[-*•▪●]|\d{1,2}[.)]|[a-z][.)]))[ \t]*")


def _row_marker(line: str) -> Tuple[bool, Optional[bool], str]:
    """(is a list row, ticked? (None = no box), the row without its marker)."""
    m = _MARKER_RE.match(line)
    if not m or not m.group(0).strip():
        return False, None, line
    rest = line[m.end():]
    if m.group("box") or m.group("ubox") or m.group("tbox"):
        ticked = bool(m.group("tick") or m.group("tick2") or m.group("tbox"))
        return True, ticked, rest
    return True, None, rest


def _row_families(row: str, strip_status: bool) -> Optional[List[str]]:
    row = row.strip().strip("|").strip()
    if strip_status:
        fams = line_name_families(row)
        if fams:
            return fams
        head = _ROW_STATUS_TAIL_RE.sub("", row)
        if head != row:
            return line_name_families(head)
        return None
    return line_name_families(row)


_BOX_RE = re.compile(r"\[[ \t]*(?P<tick>[xX\u2713\u2714*])?[ \t]*\]|(?P<ubox>[\u2610\u25a1])|(?P<tbox>[\u2611\u2612\u25a0])")


def _box_rows(line: str, next_line: Optional[str]) -> Tuple[List[Tuple[str, bool]], bool]:
    """Every checkbox on `line` with its label: [(label, ticked)], and whether
    the last box's label is `next_line` (a row wrapped after its box -
    "[ ] Cyber [ ]" / "Workers Comp")."""
    boxes = list(_BOX_RE.finditer(line))
    out: List[Tuple[str, bool]] = []
    used_next = False
    for k, m in enumerate(boxes):
        ticked = bool(m.group("tick") or m.group("tbox"))
        label = line[m.end():boxes[k + 1].start() if k + 1 < len(boxes) else len(line)].strip()
        if not label and k == len(boxes) - 1 and next_line and not _BOX_RE.search(next_line):
            label, used_next = next_line.strip(), True
        out.append((label, ticked))
    return out, used_next


def _read_list(text: str, start: int, *, requested: bool,
               multiline: bool = True) -> List[Tuple[List[str], Optional[bool]]]:
    """The rows of a list that begins at `text[start:]` (just after its label).

    The label's own line is read item by item - a row that is not a line name
    (a coverage part, an aside) is skipped and the rest still count; the list
    ends at its full stop. Each following line must be a list row: a checkbox
    line (one box per row, or several boxes on one line), a bullet or number
    whose text is a line name, or an unmarked line that is nothing but line
    names. A marked row that is not a line name is skipped; an unmarked one,
    a blank line or a full stop ends the list.
    """
    window = _strip_parentheticals(text[start:start + 2500])
    lines = window.split("\n")
    rows: List[Tuple[List[str], Optional[bool]]] = []
    skip_next = False
    for idx, raw in enumerate(lines):
        if skip_next:
            skip_next = False
            continue
        line = raw.strip()
        if idx == 0:
            if not line:
                continue
            end = _sentence_end(line)
            body = line[:end] if end >= 0 else line
            for item in re.split(r"[;,|]", body):
                if not item.strip():
                    continue
                if requested:
                    toks = _tokens(item)
                    fams, e = _leading_families(toks)
                    if fams and not _STATUS_RE.match(" ".join(t for t in toks[e:] if t not in "-:")):
                        rows.append((fams, None))
                    continue
                fams = _row_families(item, strip_status=True)
                if fams:
                    rows.append((fams, None))
            if end >= 0:
                break
            continue
        if not line or not multiline:
            break
        if _BOX_RE.search(line):
            nxt = lines[idx + 1] if idx + 1 < len(lines) else None
            boxes, skip_next = _box_rows(line, nxt)
            for label, ticked in boxes:
                end = _sentence_end(label)
                fams = _row_families(label[:end] if end >= 0 else label,
                                     strip_status=not requested)
                if fams:
                    rows.append((fams, ticked))
            continue
        is_row, ticked, rest = _row_marker(line)
        end = _sentence_end(rest)
        body = rest[:end] if end >= 0 else rest
        fams = _row_families(body, strip_status=not requested)
        if fams is None:
            if is_row:
                continue
            break
        rows.append((fams, ticked))
        if end >= 0:
            break
    return rows


def _families_from_rows(rows: List[Tuple[List[str], Optional[bool]]]) -> Set[str]:
    """Checkbox rows: when any box is ticked only the ticked rows count (the
    boxes carry the meaning); when none is, the boxes are decoration."""
    any_ticked = any(t is True for _f, t in rows)
    out: Set[str] = set()
    for fams, ticked in rows:
        if any_ticked and ticked is False:
            continue
        out.update(fams)
    return out


def _list_families(text: str, head_re, *, requested: bool) -> Set[str]:
    out: Set[str] = set()
    for m in head_re.finditer(text):
        # A heading with no colon or dash must SAY it is a list of lines
        # ("LINES NOT REQUESTED"); a bare "Not requested" on a line of its own
        # is an answer to whatever sits above it.
        if not m.group("sep") and not m.group("lines"):
            continue
        # A bare "Not requested -" is a status cell; only a colon (or a heading
        # that names lines) introduces rows on the lines below.
        multiline = bool(m.group("lines")) or m.group("sep") == ":"
        out |= _families_from_rows(_read_list(text, m.end(), requested=requested,
                                              multiline=multiline))
    return out


# ── "<line>: not requested" rows ─────────────────────────────────────────────

_LINE_STATUS_RE = re.compile(
    r"(?im)(?:^|(?<=;)|(?<=\|))[ \t]*(?:[-*•]+[ \t]*)?"
    r"(?:\[[ \t]*[xX✓✔]?[ \t]*\][ \t]*)?"
    r"(?P<x>[A-Za-z][^:\n;|]{0,60}?)[ \t]*(?:[:|]|[ \t]?[-–][ \t]*|\.{2,})[ \t]*"
    r"(?P<status>" + _STATUS + r")\b(?P<rest>[^\n;|]*)")
_STATUS_ONLY_RE = re.compile(r"(?i)^[ \t]*(?:" + _STATUS + r")[ \t]*[-–:.|]*[ \t]*$")


def _line_status_families(text: str) -> Set[str]:
    out: Set[str] = set()
    for m in _LINE_STATUS_RE.finditer(text):
        rest = m.group("rest") or ""
        if _CONDITION_RE.search(rest) or _partial(rest):
            continue
        fams = line_name_families(m.group("x"))
        if fams:
            out.update(fams)
    # The status on the line BELOW the name - a two-column table read
    # column-first ("Workers Compensation\nNot requested").
    lines = text.split("\n")
    for i in range(len(lines) - 1):
        if _STATUS_ONLY_RE.match(lines[i + 1]):
            is_row, _t, rest = _row_marker(lines[i].strip())
            fams = line_name_families(rest)
            if fams:
                out.update(fams)
    return out


# ── Sentences ────────────────────────────────────────────────────────────────

_DECLINE_CUE_RE = re.compile(
    r"(?i)\b(?:(?:is|are)\s+not\s+(?:being\s+)?(?:requested|marketed|quoted|wanted|needed)"
    r"|will\s+not\s+be\s+(?:requested|marketed|quoted)"
    r"|(?:is|are)\s+not\s+(?:a\s+(?:line|part)\s+of|part\s+of|included\s+in)\s+(?:this|the)\s+"
    r"(?:submission|request|program(?:me)?|marketing|quote)"
    r"|(?:is|are)\s+(?:excluded|omitted|removed)\s+from\s+(?:this|the)\s+"
    r"(?:submission|request|program(?:me)?|marketing|quote)"
    r"|(?:is|are|will\s+be)\s+(?:being\s+)?(?:quoted|marketed)\s+separately)\b")
_REQUEST_CUE_RE = re.compile(r"(?i)\b(?:is|are)\s+(?:also\s+)?(?:being\s+)?requested\b")
_SUBJECT_BOUNDARIES = frozenset({"and", "but", "that", "so", ",", ";", ":", "-", "|",
                                 "also", "however", "currently", "additionally", "further",
                                 "furthermore", "finally", "lastly", "otherwise", "note",
                                 "therefore", "thus"})
_VERBS = frozenset({"is", "are", "was", "were", "will", "shall", "would", "has", "have",
                    "had", "remains", "remain", "stays", "stay", "renews", "renew",
                    "continues", "continue", "goes", "sits", "expires", "expire"})


_SENT_BREAK_RE = re.compile(r"[.!?;](?=\s|$)|\n[ \t]*\n")


def _is_abbreviation_stop(text: str, j: int) -> bool:
    word = re.search(r"([A-Za-z]+)\s*$", text[max(0, j - 30):j])
    return bool(word and (len(word.group(1)) == 1 or word.group(1).lower() in _ABBREVIATIONS))


def _sentence_span(text: str, pos: int, end_pos: int) -> Optional[Tuple[int, int]]:
    """[start, end) of the sentence around text[pos:end_pos], or None when no
    start is found within 1,500 characters. Ends: a full stop (not an initial
    or abbreviation), "!", "?", ";" or a blank line."""
    lo = max(0, pos - 1500)
    start = None
    for m in _SENT_BREAK_RE.finditer(text, lo, pos):
        if text[m.start()] == "." and _is_abbreviation_stop(text, m.start()):
            continue
        start = m.end()
    if start is None:
        if lo == 0:
            start = 0
        else:
            nl = text.find("\n", lo, pos)
            if nl < 0:
                return None
            start = nl + 1
    hi = min(len(text), end_pos + 1500)
    end = hi
    for m in _SENT_BREAK_RE.finditer(text, end_pos, hi):
        if text[m.start()] == "." and _is_abbreviation_stop(text, m.start()):
            continue
        end = m.start()
        break
    return start, end


def _tokens_with_line_starts(text: str) -> List[Tuple[str, bool]]:
    out: List[Tuple[str, bool]] = []
    for ln_i, line in enumerate(text.split("\n")):
        toks = _tokens(line)
        for j, t in enumerate(toks):
            out.append((t, j == 0 and ln_i > 0))
    return out


def _subject_families(pre: str) -> Optional[List[str]]:
    """The line the clause before a cue is ABOUT, or None.

    Its SUBJECT is the run of words right before the verb: it must be nothing
    but line names and start the clause (sentence start, a line start, or after
    "and" / "but" / "that" / a comma). When the verb follows "and" / "but" /
    a comma ("Workers comp stays with TEM and is not marketed") the subject is
    the sentence's leading noun phrase, which must be followed by a verb.
    """
    toks = _tokens_with_line_starts(pre)
    words = [t for t, _ls in toks]
    if not words:
        return None
    if words[-1] in ("and", "but", ","):
        starts = [0] + [i for i, (_t, ls) in enumerate(toks) if ls] + \
                 [i + 1 for i, t in enumerate(words) if t in ("that", ":")]
        for c in sorted(set(starts)):
            fams, e = _leading_families(words[c:])
            if fams:
                nxt = words[c + e] if c + e < len(words) else None
                if nxt in _VERBS or nxt == ",":
                    return fams
        return None
    for s in range(len(words)):
        if s == 0 or words[s - 1] in _SUBJECT_BOUNDARIES or toks[s][1]:
            fams = families_of_tokens(words[s:])
            if fams:
                return fams
    return None


def _sentence_families(text: str, cue_re) -> Set[str]:
    out: Set[str] = set()
    for m in cue_re.finditer(text):
        span = _sentence_span(text, m.start(), m.end())
        if span is None:
            continue
        s, e = span
        if e < len(text) and text[e] == "?":
            continue                              # a question states nothing
        pre, post = text[s:m.start()], text[m.end():e]
        if _CONDITION_RE.search(pre) or _CONDITION_RE.search(_clause_head(post)):
            continue
        if _partial(post):
            continue
        fams = _subject_families(pre)
        if fams:
            out.update(fams)
    return out


_ACTIVE_DECLINE_RE = re.compile(
    r"(?i)\b(?:not|no\s+longer)\s+(?:requesting|marketing|seeking\s+(?:a\s+)?quotes?\s+(?:for|on)"
    r"|asking\s+(?:you\s+)?to\s+quote)\s+")
_QUOTE_SEPARATELY_RE = re.compile(
    r"(?i)\bquote[sd]?\s+(?P<np>(?:[^.;:\n]|\n(?![ \t]*\n)){1,80}?)\s+separately\b")
_ALL_EXCEPT_RE = re.compile(r"(?i)\b(?:quote|market)\s+all\s+(?:lines|coverages)(?:\s+of\s+business)?"
                            r"\s+(?:except|excluding|other\s+than|but)\s+")
_EXCLUDING_FIRST_RE = re.compile(r"(?im)(?:^|(?<=[.;:])\s+)[ \t]*(?:excluding|except\s+for)\s+"
                                 r"(?P<np>[^,.;\n]{1,60}),\s*(?:please\s+)?(?:quote|market)\b")


def _object_families(text: str, start: int) -> Optional[List[str]]:
    """The object starting at `text[start:]`: nothing but line names up to the
    end of its clause (a time phrase - "this year", "at this time" - allowed)."""
    span = _sentence_span(text, start, start)
    if span is None:
        return None
    obj = _clause_head(text[start:span[1]])
    obj = _TIME_TAIL_RE.sub("", obj.rstrip())
    return line_name_families(obj)


def _active_families(text: str) -> Set[str]:
    out: Set[str] = set()
    for rx in (_ACTIVE_DECLINE_RE, _ALL_EXCEPT_RE):
        for m in rx.finditer(text):
            span = _sentence_span(text, m.start(), m.end())
            if span is None or _CONDITION_RE.search(text[span[0]:span[1]]):
                continue
            fams = _object_families(text, m.end())
            if fams:
                out.update(fams)
    for m in _QUOTE_SEPARATELY_RE.finditer(text):
        fams = line_name_families(m.group("np"))
        if fams:
            out.update(fams)
    for m in _EXCLUDING_FIRST_RE.finditer(text):
        fams = line_name_families(m.group("np"))
        if fams:
            out.update(fams)
    return out


# ── What the documents state IS requested (contests a decline) ───────────────

_PLEASE_QUOTE_RE = re.compile(
    r"(?i)\b(?:please\s+quote|(?:we\s+are\s+|we're\s+)?requesting(?:\s+(?:a\s+)?quotes?\s+(?:for|on))?"
    r"|request(?:s|ing)?\s+(?:a\s+)?quotes?\s+(?:for|on))\s+(?P<obj>[^.;\n]{1,200})")


def _quoted_families(text: str) -> Set[str]:
    """Lines a "please quote ..." / "requesting ..." sentence asks for. Read
    generously - a false REQUEST only keeps a line in the submission."""
    out: Set[str] = set()
    for m in _PLEASE_QUOTE_RE.finditer(text):
        pre = text[max(0, m.start() - 12):m.start()].lower()
        if re.search(r"\b(?:not|no\s+longer)\s*$", pre):
            continue
        obj = m.group("obj")
        if re.search(r"(?i)\bseparately\b", obj):
            continue
        for item in re.split(r"(?i),|;|\band\b|\bplus\b", obj):
            toks = _tokens(item)
            fams, e = _leading_families(toks)
            if fams and not _STATUS_RE.match(" ".join(toks[e:])):
                out.update(fams)
    return out


def lines_requested(full_text: str) -> List[str]:
    """Line families the documents state ARE requested."""
    text = _strip_parentheticals(str(full_text or ""))
    if not text.strip():
        return []
    got = _list_families(text, _REQUEST_HEAD_RE, requested=True)
    got |= _sentence_families(text, _REQUEST_CUE_RE)
    got |= _quoted_families(text)
    return sorted(got)


def lines_not_requested(full_text: str) -> List[str]:
    """Line families the documents state are NOT part of this submission."""
    raw = str(full_text or "")
    if not raw.strip():
        return []
    text = _strip_parentheticals(raw)
    declined = _list_families(text, _DECLINE_HEAD_RE, requested=False)
    declined |= _line_status_families(text)
    declined |= _sentence_families(text, _DECLINE_CUE_RE)
    declined |= _active_families(text)
    if not declined:
        return []
    declined -= set(lines_requested(raw))
    return sorted(declined)


# ── Carried elsewhere ────────────────────────────────────────────────────────

# A decline says the line is not part of THIS submission; whether the insured
# still CARRIES it is a different question (employees without WC, the
# umbrella's Employers Liability). Answered only where the statement says so:
# "stays with Tennessee Employers Mutual", "placed separately", "already with
# you", "insured by X", "written through the state fund".
_CARRIED_CUE_RE = re.compile(
    r"(?i)\b(?:(?:stays?|remains?|renews?|continues?)\s+with"
    r"|(?:placed|insured|written|carried)\s+(?:separately|elsewhere|by|with|through)"
    r"|already\s+(?:with|written|placed|insured|in\s+force|carried)"
    r"|with\s+(?:the\s+)?(?:incumbent|state\s+fund|current\s+carrier|another\s+carrier)"
    r"|in\s+force\s+with|monopolistic|state\s+fund)\b")
_NOT_CARRIED_CUE_RE = re.compile(
    r"(?i)\b(?:no\s+(?:employees|staff|coverage|exposure|need)|not\s+(?:carried|in\s+force|covered)"
    r"|declined\s+it|insured\s+declined|never\s+(?:carried|had))\b")


def lines_carried_elsewhere(full_text: str, declined: Iterable[str]) -> List[str]:
    """Of the `declined` families, those a decline statement says the insured
    carries elsewhere - the sentence naming the line, or the aside beside it
    in a list, states it and nothing there says the opposite."""
    want = {str(d) for d in (declined or []) if d}
    raw = str(full_text or "")
    if not want or not raw.strip():
        return []
    found: Set[str] = set()
    # Sentences: the decline sentence itself ("Workers compensation stays with
    # TEM and is NOT being marketed").
    # Attribution is looser than for the decline itself - only lines ALREADY
    # read as declined are considered - so a sentence that merely STARTS with
    # the line counts ("Workers Compensation for Oregon operations is written
    # separately through the state fund and is not part of this submission").
    flat = _strip_parentheticals(raw)
    for m in _DECLINE_CUE_RE.finditer(flat):
        span = _sentence_span(flat, m.start(), m.end())
        if span is None:
            continue
        s, e = span
        sentence = flat[s:e]
        if not _CARRIED_CUE_RE.search(sentence) or _NOT_CARRIED_CUE_RE.search(sentence):
            continue
        fams = set(_subject_families(flat[s:m.start()]) or [])
        for ln in flat[s:m.start()].split("\n"):
            lead, _e = _leading_families(_tokens(ln))
            if lead:
                fams.update(lead)
                break
        found.update(f for f in fams if f in want)
    # List items with their aside: "workers compensation (stays with TEM ...)".
    for m in re.finditer(r"(?P<name>[A-Za-z][A-Za-z' &/-]{1,60}?)\s*\((?P<aside>(?:[^()\n]|\n(?![ \t]*\n)){0,400})\)",
                         raw):
        fams = line_name_families(re.split(r"[;:,\n]", m.group("name"))[-1])
        if not fams:
            continue
        aside = m.group("aside")
        if _CARRIED_CUE_RE.search(aside) and not _NOT_CARRIED_CUE_RE.search(aside):
            found.update(f for f in fams if f in want)
    return sorted(found)
