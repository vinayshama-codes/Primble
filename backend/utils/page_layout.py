"""utils/page_layout.py - reading-order repair and header-anchored tables for one page.

Pure functions over "word" dicts ``{x0, x1, top, bottom, text}``. pdfplumber words
(points) and Google Vision words (pixels) both fit: every threshold is relative to
the median word height on the page, so one implementation serves native and
scanned pages alike. No service imports. Full history and measurements in
``extraction_arch_change.md`` at the repo root - read it before tuning anything.

Four jobs.

-1. ``despaced_words`` - letter-spaced (teletype) lines. On EMC's auto and
   inland-marine declarations every glyph is drawn with tracking, so the gap
   BETWEEN LETTERS (6.56pt) equals the gap between WORDS on an ordinary line in
   the same document (6.56pt, against 0.07pt between its letters). pdfplumber
   cannot separate those at any fixed tolerance, so a policy number arrives as
   ``6 C 7 - 4 0 - 0 2---26`` - a string that reached a client's ACORD 125. The
   ambiguity is only per-character: per LINE, a letter-spaced line's small gap is
   about a full glyph wide, and its real word breaks are far wider still.

0. ``column_bands`` - two-column reading order (added 2026-08-22, second pass).
   A policy form is printed in two columns. Read straight across, the left
   column's exclusion and the right column's exception splice into sentences the
   document does not contain. Measured on the client's 271-page package: 164 of
   271 pages. The gutter is found by how few lines STRADDLE an x, not by a clean
   ink projection - the real channel is 2-3pt wide, so a textbook XY-cut finds
   nothing. Only bands whose text is RUNNING PROSE are reordered: the same page
   can carry `Named Insured | Producer` (which reordering would help) and
   `Each Occurrence Limit | $1,000,000` (which it would destroy), and no
   geometric test separates them - see ``column_bands``.

1. ``page_words`` / ``page_text`` - character interleave repair.
   pdfplumber's default ``extract_text()`` sorts CHARACTERS left to right across a
   line. When two text runs overlap in x - a claim description that overruns into
   the PAID column - their characters are riffled together::

       "party" + "$4,850"  ->  "pa$rt4y,850"

   Measured on the client's loss run: the description ends at x=384 and the PAID
   column starts at x=360. The repair is SCOPED to the lines that show the defect:
   text-flow segmentation (the PDF's own character order, which keeps each run
   whole) restricted to that line's band, then words sorted by x0 to restore
   reading order. Text flow applied to the whole page is NOT safe and was
   measured: it makes the two-column reflow fixture worse (bare labels 9 -> 12)
   and reorders 105 lines on ``templates/ACORD_125.pdf``, because a PDF's stream
   order is not its reading order on real forms. On a page with no interleaved
   line, ``page_words`` returns exactly ``page.extract_words()`` and ``page_text``
   returns exactly ``page.extract_text()`` - byte-identical, pinned by test.

2. ``detect_tables`` / ``render_tables`` - whitespace-aligned tables.
   Insurance schedules are aligned by position, not ruled by lines, so
   pdfplumber's default ``extract_tables()`` finds nothing (0 of 4 on the test
   package) and its text strategy fabricates garbage (``COMMERCIAL PA | CKAG | E``).
   This detector anchors columns on a HEADER row's left edges and assigns each
   body cell by its own left edge - data overflows to the right, headers do not.
   A wrapped continuation row (first cell not in column 0) folds into the row
   above; a line whose first cell ends in ``:`` is a summary line and ends the
   table. Structural rules only - no vocabulary, no "Total" list.
"""
from __future__ import annotations

import logging
import os
import statistics
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

Word = Dict[str, Any]

__all__ = [
    "page_words", "page_text", "detect_tables", "render_tables",
    "interleaved_bands", "column_bands", "despaced_words", "vision_words",
    "TABLE_OPEN", "TABLE_CLOSE",
]


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_on(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off")


# ── Interleave detection (section 1.4 of extraction_arch_change.md) ─────────
# Adjacent-character overlap ratio = overlap / min(width), on an x-sorted line.
# Kerning on a Word-generated page peaks at 0.40; a riffled line sits above 1.0
# and alternates for several characters. Both rules measured at zero false
# positives across the corpus.
_OVERLAP_PAIR     = _env_float("PAGE_LAYOUT_OVERLAP_PAIR", 0.5)
_OVERLAP_HARD     = _env_float("PAGE_LAYOUT_OVERLAP_HARD", 0.9)
_OVERLAP_MIN_PAIRS = 2
_Y_TOL            = 3.0          # pdfplumber's own default y_tolerance for lines
_BASELINE_TOL     = 1.0          # strict same-baseline tolerance for riffle DETECTION only
_DEINTERLEAVE_ON  = _env_on("PAGE_LAYOUT_DEINTERLEAVE")

# ── Table detection ──────────────────────────────────────────────────────────
# Gap between consecutive words that separates two CELLS, as a fraction of the
# median word height. Measured distribution on every insurance page in the
# corpus: inter-word spaces sit below 0.6h, column gaps at or above 1.0h, with
# 0-2 gaps per page in between. 0.75 is in the valley.
_CELL_GAP_RATIO   = _env_float("PAGE_LAYOUT_CELL_GAP", 0.75)
_ALIGN_TOL_RATIO  = 0.5          # a cell "starts in" a column within half a word height
_ANCHOR_TOL_RATIO = 0.15         # a word starts ON a column anchor within ~1.4pt at 9pt text
_MIN_HEADER_CELLS = 3
_MIN_ALIGNED_ROWS = 0.6          # fraction of data rows that must truly align to >= 2 columns
_SECTION_LOOKBACK = 3
_SECTION_MAX_LEN  = 60
_SOUP_RATIO       = 0.25         # > this fraction of single-letter alphabetic tokens = not a table
# Prose gates. Measured on 40 genuine tables vs 48 policy-wording blocks; every one
# of these leaves the genuine set untouched at the chosen value (see _is_header and
# _is_running_prose).
_HEADER_LOWER_MAX = 0.25         # header cells starting mid-sentence (genuine max: 0.00)
_ROW_LOWER_MAX    = 0.5          # rows starting mid-sentence (genuine max: 0.40)
_ROW_LOWER_SOFT   = 0.25         # weaker row test, only together with the tail test
_ROW_TAIL_SOFT    = 0.25         # cells ending on a comma / semicolon / function word

# ── Two-column reading order ────────────────────────────────────────────────
# A gutter is judged by how few lines STRADDLE it, not by clean whitespace: the
# real gutter in the client's package is 2-3pt wide, so an ink-projection XY-cut
# finds nothing there (measured page 151: widest zero-ink run 2pt, but ZERO lines
# cross it). PAGE_LAYOUT_COLUMNS=0 disables.
# Letter-spaced (teletype) lines: the gap between GLYPHS equals a word gap on an
# ordinary line. Detected when the median gap is at least half a glyph wide, then
# re-split at gaps clearly wider than that tracking. PAGE_LAYOUT_DESPACE=0 disables.
_DESPACE_ON             = _env_on("PAGE_LAYOUT_DESPACE")
_DESPACE_MIN_RATIO      = _env_float("PAGE_LAYOUT_DESPACE_RATIO", 0.5)
_DESPACE_BREAK_RATIO    = _env_float("PAGE_LAYOUT_DESPACE_BREAK", 1.8)
_DESPACE_MIN_CHARS      = 6
_DESPACE_MAX_GROWTH     = 0        # rebuilt words must not exceed the words they replace
_DESPACE_MIN_SINGLE_FRAC = _env_float("PAGE_LAYOUT_DESPACE_SINGLES", 0.6)  # evidence of the defect

_COLUMNS_ON             = _env_on("PAGE_LAYOUT_COLUMNS")
_GUTTER_MAX_CROSS_FRAC  = _env_float("PAGE_LAYOUT_GUTTER_CROSS", 0.05)
_GUTTER_MIN_BOTH        = 4      # lines with content on both sides, or it is not a gutter
_COLUMN_MIN_LINES       = 4      # a band shorter than this is not worth reordering
_COLUMN_MIN_BOTH        = 3
_COLUMN_MIN_WORDS       = 40
_GUTTER_EDGE_FRAC       = _env_float("PAGE_LAYOUT_GUTTER_EDGE", 0.10)  # top/bottom band excluded from gutter SCORING only
# Horizontal band split (the other half of the XY-cut). A gap this many times the
# page's own median line pitch starts a new band. Page 205: 60.5pt against a 5-8pt
# pitch separates the identity block from the limits table.
# 4.0, not 2.5: at 2.5 the 19pt gap under `Named Insured | Producer` cut the
# header away from its own address block and left a 1-line band nothing can use.
# Only a gap several times the pitch marks a real change of section.
_HBAND_GAP_RATIO        = _env_float("PAGE_LAYOUT_HBAND_RATIO", 4.0)
_HBAND_MIN_GAP          = _env_float("PAGE_LAYOUT_HBAND_MIN", 6.0)
# Side-by-side identity blocks (`Named Insured` | `Producer`).
_PARALLEL_MIN_LINES      = 3
_PARALLEL_MIN_PAIRED     = 3      # rows with real content in BOTH columns
_PARALLEL_MAX_CELL_CHARS = 45     # an identity line, not a form-grid label
_PROSE_MIN_LINES         = 8      # a real two-column prose run; ACORD false positives are 4-6
_PARALLEL_LABEL_MAX_WORDS = 4     # a heading, not a sentence
_PARALLEL_MAX_VALUE_FRAC = 0.34   # a right column of AMOUNTS is a table, never a block
_TABLES_ON        = _env_on("PAGE_LAYOUT_TABLES")

TABLE_OPEN  = "[Table - page {page}{section}]"
TABLE_CLOSE = "[End table]"


# ─────────────────────────────────────────────────────────────────────────────
# Line clustering - pdfplumber's own algorithm, so the rebuilt text is identical
# to extract_text() on every page where nothing was repaired (35/35 measured).
# ─────────────────────────────────────────────────────────────────────────────

def _cluster_lines(objs: Sequence[Word], key: str = "top") -> List[List[Word]]:
    if not objs:
        return []
    try:
        from pdfplumber.utils import cluster_objects
        lines = cluster_objects(list(objs), lambda o: o[key], _Y_TOL)
    except Exception:                                    # pragma: no cover - no pdfplumber
        lines = _chain_cluster(objs, key)
    return [sorted(line, key=lambda o: o["x0"]) for line in lines]


def _chain_cluster(objs: Sequence[Word], key: str, tol: float = _Y_TOL) -> List[List[Word]]:
    """Same rule as pdfplumber.utils.cluster_objects: sort by key, open a new
    cluster when the gap to the PREVIOUS value exceeds the tolerance."""
    ordered = sorted(objs, key=lambda o: o[key])
    out: List[List[Word]] = []
    cur: List[Word] = []
    last: Optional[float] = None
    for o in ordered:
        if cur and last is not None and o[key] - last > tol:
            out.append(cur)
            cur = []
        cur.append(o)
        last = o[key]
    if cur:
        out.append(cur)
    return out


def _line_text(line: Sequence[Word]) -> str:
    return " ".join(w["text"] for w in line)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Interleave repair
# ─────────────────────────────────────────────────────────────────────────────

def interleaved_bands(chars: Sequence[Word]) -> List[Tuple[float, float]]:
    """(top, bottom) of every line whose x-sorted characters collide.

    Only upright, non-blank characters take part: a diagonal watermark crossing a
    line is not a riffle, and a space glyph's box may legitimately overlap anything.

    Lines are clustered on a STRICT baseline (``_BASELINE_TOL``), not the 3pt
    chain pdfplumber uses for reading lines. Measured on the ACORD templates: two
    stacked 6pt box labels 5.5pt apart ("TYPE" over "BODY") are bridged into one
    3pt-chain cluster by the glyphs between them, and their x-sorted characters
    then "collide" at ratio 1.0 - a false riffle on 10 of 12 template pages. A real
    riffle is two runs on ONE baseline; the pair test below requires the two boxes
    to overlap vertically as well, so the rule holds whatever the clustering does.
    """
    ink = [c for c in chars if str(c.get("text", "")).strip() and c.get("upright", True)]
    bands: List[Tuple[float, float]] = []
    for line in _chain_cluster(ink, "top", _BASELINE_TOL):
        line = sorted(line, key=lambda c: c["x0"])
        pairs = 0
        hard = False
        for a, b in zip(line, line[1:]):
            w = min(a["x1"] - a["x0"], b["x1"] - b["x0"])
            h = min(a["bottom"] - a["top"], b["bottom"] - b["top"])
            if w <= 0 or h <= 0:
                continue
            v_overlap = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"])
            if v_overlap < 0.5 * h:
                continue                                # different baselines - not a riffle
            ratio = (a["x1"] - b["x0"]) / w
            if ratio >= _OVERLAP_HARD:
                hard = True
            if ratio >= _OVERLAP_PAIR:
                pairs += 1
        if hard or pairs >= _OVERLAP_MIN_PAIRS:
            bands.append((min(c["top"] for c in line), max(c["bottom"] for c in line)))
    return bands


def _in_bands(w: Word, bands: Sequence[Tuple[float, float]]) -> bool:
    mid = (w["top"] + w["bottom"]) / 2.0
    return any(t - _Y_TOL <= mid <= b + _Y_TOL for t, b in bands)


def _despace_line(line: Sequence[Word], chars: Sequence[Word]) -> Optional[List[Word]]:
    """Rejoin one LETTER-SPACED line, or None if it is ordinary text.

    Teletype-style declarations pages (EMC's auto and inland-marine sections) draw
    every glyph with tracking, so the gap BETWEEN LETTERS equals the gap between
    words on a normal line - measured on the client's package: 6.56pt letter
    tracking against a 6.41pt glyph, where ordinary text has 0.07pt between
    letters and 6.56pt between words. pdfplumber cannot separate those two cases
    at its default 3pt tolerance, so `POLICY NUMBER 6E7-40-02---26` arrives as
    `P O L I C Y  N U M B E R  6 E 7 - 4 0 - 0 2---26`. That exact string
    (`6 C 7 - 4 0 - 0 2---26`) reached a client's ACORD 125.

    The two cases ARE separable per line, because the choice is only ambiguous in
    isolation: on a letter-spaced line the small gap is about a full glyph wide.
    Detect on that ratio, then re-split at gaps clearly wider than the tracking -
    the line's own word breaks (19.5pt and 90.9pt on the measured line) stand well
    clear of it. 2,247 lines on 158 of 271 pages of the client's package.
    """
    if len(line) < _DESPACE_MIN_CHARS:
        return None
    widths = [c["x1"] - c["x0"] for c in line if c["x1"] > c["x0"]]
    # Negative gaps are kerning - clamp, never DROP them. Dropping them left only
    # the wide column gaps in the sample, so an ordinary three-cell table row
    # scored a median "tracking" of 14pt and was rebuilt as letter-spaced text.
    gaps = [max(0.0, b["x0"] - a["x1"]) for a, b in zip(line, line[1:])]
    if not widths or not gaps:
        return None
    glyph = statistics.median(widths)
    track = statistics.median(gaps)
    if glyph <= 0 or track / glyph < _DESPACE_MIN_RATIO:
        return None                                   # ordinary text - letters touch

    out: List[Word] = []
    cur: List[Word] = [line[0]]
    for a, b in zip(line, line[1:]):
        if (b["x0"] - a["x1"]) > track * _DESPACE_BREAK_RATIO:
            out.append(_join_chars(cur))
            cur = [b]
        else:
            cur.append(b)
    out.append(_join_chars(cur))
    return out


def _join_chars(chars: Sequence[Word]) -> Word:
    return {
        "x0": chars[0]["x0"],
        "x1": chars[-1]["x1"],
        "top": min(c["top"] for c in chars),
        "bottom": max(c["bottom"] for c in chars),
        "text": "".join(c["text"] for c in chars),
    }


def despaced_words(page) -> Tuple[List[Word], int]:
    """``(words, rejoined_line_count)`` with letter-spaced lines rebuilt from chars.

    Only lines that fail the ordinary-text test are rebuilt; every other line
    keeps pdfplumber's own words untouched, so a page with no tracking is
    byte-identical (pinned by test).
    """
    words = page.extract_words() or []
    if not _DESPACE_ON or not words:
        return words, 0
    try:
        chars = [c for c in page.chars if str(c.get("text", "")).strip()
                 and c.get("upright", True)]
    except Exception:                                  # noqa: BLE001
        return words, 0
    if not chars:
        return words, 0

    # A genuinely letter-spaced line is one pdfplumber broke into SINGLE
    # CHARACTERS. Page 241's contents page has wide dot-leader spacing that looks
    # like tracking, and rebuilding it welded `Coverage A -` into `CoverageA-`,
    # destroying word boundaries. Requiring the evidence of the defect itself -
    # single-character words on that line - separates the two exactly.
    def _is_shredded(top: float, bottom: float) -> bool:
        # Alphanumeric words only. A contents page's dot leaders are 25 separate
        # one-character "words" on their own, which made page 241 score 0.89 and
        # weld `Coverage A -` into `CoverageA-`.
        mid_hits = [w for w in words
                    if top - _Y_TOL <= (w["top"] + w["bottom"]) / 2.0 <= bottom + _Y_TOL
                    and any(ch.isalnum() for ch in w["text"])]
        if len(mid_hits) < _DESPACE_MIN_CHARS:
            return False
        singles = sum(1 for w in mid_hits if len(w["text"]) == 1)
        return singles / len(mid_hits) >= _DESPACE_MIN_SINGLE_FRAC

    rebuilt: List[Word] = []
    touched: List[Tuple[float, float]] = []
    count = 0
    for line in _cluster_lines(chars):
        joined = _despace_line(line, chars)
        if joined is None:
            continue
        if not _is_shredded(min(c["top"] for c in line), max(c["bottom"] for c in line)):
            continue
        rebuilt.extend(joined)
        touched.append((min(c["top"] for c in line), max(c["bottom"] for c in line)))
        count += 1
    if not count:
        return words, 0

    # Replace ONLY words whose own box sits inside a rebuilt line. `_in_bands`
    # pads by _Y_TOL, which on a tight page swallowed the neighbouring line and
    # deleted its words outright - measured as 112 pages of character loss.
    def _inside(w: Word) -> bool:
        return any(t <= (w["top"] + w["bottom"]) / 2.0 <= b for t, b in touched)

    kept = [w for w in words if not _inside(w)]
    dropped = len(words) - len(kept)
    if dropped < len(rebuilt) - _DESPACE_MAX_GROWTH * max(1, count):
        # The rebuild should replace roughly as many words as it produces. A wild
        # mismatch means the band mapping is wrong, and shipping it would lose or
        # duplicate text - keep pdfplumber's words instead.
        logger.warning("page_layout: despacing replaced %d words with %d on %d line(s) "
                       "- keeping the original words", dropped, len(rebuilt), count)
        return words, 0
    return kept + rebuilt, count


def page_words(page) -> Tuple[List[Word], int]:
    """Words for a pdfplumber page or crop, with interleaved lines repaired.

    Returns ``(words, repaired_line_count)``. Zero repaired lines means ``words``
    is exactly ``page.extract_words()``. A repaired line's words come from
    ``extract_words(use_text_flow=True)`` restricted to that line's band - the
    stream order keeps each run whole - and are returned unsorted; callers sort
    by x0 within a line, which restores reading order.
    """
    words, despaced = despaced_words(page)
    if not _DEINTERLEAVE_ON or not words:
        return words, despaced
    try:
        bands = interleaved_bands(page.chars)
    except Exception as ex:                              # noqa: BLE001 - never cost a page its text
        logger.debug("page_layout: interleave scan failed: %s", ex)
        return words, despaced
    if not bands:
        return words, despaced
    try:
        flow = page.extract_words(use_text_flow=True) or []
    except Exception as ex:                              # noqa: BLE001
        logger.warning("page_layout: text-flow extraction failed, keeping default words: %s", ex)
        return words, despaced
    kept = [w for w in words if not _in_bands(w, bands)]
    repaired = [w for w in flow if _in_bands(w, bands)]
    if not repaired:
        # Text flow produced nothing in the band - keep what we had rather than
        # delete a line. Loud, because it means the detector and the repair disagree.
        logger.warning("page_layout: %d interleaved line(s) detected but text flow "
                       "returned no words there - line(s) left as extracted", len(bands))
        return words, despaced
    return kept + repaired, len(bands) + despaced


def _left_right(line: Sequence[Word], gx: float) -> Tuple[List[Word], List[Word], bool]:
    left = [w for w in line if w["x1"] <= gx]
    right = [w for w in line if w["x0"] >= gx]
    crosses = any(w["x0"] < gx < w["x1"] for w in line)
    return left, right, crosses


def _best_gutter(lines: Sequence[Sequence[Word]], words: Sequence[Word]) -> Optional[float]:
    """The x that most cleanly separates two columns, or None.

    Scored by how few lines a word STRADDLES it, not by zero ink coverage. On the
    client's 271-page package the true gutter is only 2-3pt of literal whitespace -
    a plain XY-cut projection finds nothing - but zero lines cross it. Restricted
    to the middle half of the text block so a margin can never win.
    """
    xs0 = [w["x0"] for w in words]
    xs1 = [w["x1"] for w in words]
    lo, hi = min(xs0), max(xs1)
    if hi - lo < 100:
        return None
    a, b = int(lo + (hi - lo) * 0.25), int(lo + (hi - lo) * 0.75)

    # Running headers and footers span the full width and would veto every
    # candidate on their own. Measured on the client's package: page 12's four
    # header lines ("AAIS", "CL 0600 01 15", "-- PLEASE READ THIS CAREFULLY --",
    # the endorsement title) put crossings at 7.5% of the page and blocked a
    # gutter that ZERO body lines cross. They are excluded from the SCORE only -
    # they still end a band in `column_bands`, so they are never reordered.
    tops = [min(w["top"] for w in line) for line in lines]
    bots = [max(w["bottom"] for w in line) for line in lines]
    y0, y1 = min(tops), max(bots)
    margin = (y1 - y0) * _GUTTER_EDGE_FRAC
    body = [line for line, t, bm in zip(lines, tops, bots)
            if t >= y0 + margin and bm <= y1 - margin]
    if len(body) < _COLUMN_MIN_LINES:
        body = list(lines)

    scored: List[Tuple[int, int, int]] = []
    for gx in range(a, b):
        crossings = 0
        both = 0
        for line in body:
            l, r, c = _left_right(line, gx)
            if c:
                crossings += 1
            elif l and r:
                both += 1
        scored.append((gx, crossings, both))
    if not scored:
        return None

    fewest = min(s[1] for s in scored)
    if fewest > max(1, _GUTTER_MAX_CROSS_FRAC * len(body)):
        return None

    # Many x values tie at the fewest crossings - they are the whitespace channel.
    # Take the MIDDLE of the widest such run, not the first or the best-scoring
    # one. A right column with a hanging indent ("2." outdented from its own
    # paragraph) leaves a narrow secondary channel between the number and its
    # text; picking any x inside it strands the number in the left column, which
    # is exactly what page 12 of the client's package did before this.
    runs: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for gx, crossings, _both in scored:
        if crossings == fewest:
            if start is None:
                start = gx
        elif start is not None:
            runs.append((start, gx))
            start = None
    if start is not None:
        runs.append((start, scored[-1][0] + 1))
    if not runs:
        return None
    lo_x, hi_x = max(runs, key=lambda r: r[1] - r[0])
    gx = (lo_x + hi_x - 1) / 2.0

    both = sum(1 for line in body if all(_left_right(line, gx)[:2]))
    if both < _GUTTER_MIN_BOTH:
        return None
    return gx


def _horizontal_bands(lines: Sequence[Sequence[Word]]) -> List[Tuple[int, int]]:
    """Split lines at vertical gaps clearly wider than this page's line spacing.

    The horizontal half of a recursive XY-cut, and it must run FIRST. Page 205 of
    the client's package puts a two-column identity block directly above a
    single-column limits block; scored as one page they merge into one band and
    nothing can be done with either. The gap between them is 60.5pt against a
    5-8pt line pitch, so a band split separates them exactly.
    """
    if len(lines) < 2:
        return [(0, len(lines))]
    tops = [min(w["top"] for w in l) for l in lines]
    bots = [max(w["bottom"] for w in l) for l in lines]
    gaps = [max(0.0, tops[i] - bots[i - 1]) for i in range(1, len(lines))]
    pitch = statistics.median(gaps) if gaps else 0.0
    # A page whose lines already sit far apart (a sparse cover sheet) has no
    # meaningful "large" gap; fall back to one band rather than shredding it.
    floor = max(pitch * _HBAND_GAP_RATIO, _HBAND_MIN_GAP)
    cuts = [0] + [i for i, g in enumerate(gaps, start=1) if g >= floor] + [len(lines)]
    return [(a, b) for a, b in zip(cuts, cuts[1:]) if b > a]


def column_bands(words: Sequence[Word]) -> List[Tuple[int, int, float]]:
    """Runs of consecutive lines that are two columns of RUNNING PROSE, as
    ``(first_line, last_line_exclusive, gutter_x)`` over ``_cluster_lines(words)``.

    Why prose only. A policy form and a declarations page are the same geometry: on
    page 205 of the client's package ONE gutter serves both `Named Insured |
    Producer` and `Each Occurrence Limit | $1,000,000`. Reordering the first is
    right; reordering the second orphans every limit from its amount. Nothing in
    the layout distinguishes them - measured - so the test is the text, reusing the
    same signal the table gates use: prose continues across lines, a label:value
    row does not. Measured on the 271-page package: 141 prose bands found, 8
    label/value bands correctly left alone (lowercase-start 0.59-0.82 vs 0.00).

    The consequence of the narrow rule is that the `Named Insured | Producer` merge
    is NOT repaired here. That is deliberate: splitting a label/value row would
    orphan values on every declarations page in the book, and blank-over-wrong
    applies to reading order too.
    """
    if not _COLUMNS_ON or len(words) < _COLUMN_MIN_WORDS:
        return []
    lines = _cluster_lines(words)
    if len(lines) < _COLUMN_MIN_LINES:
        return []

    out: List[Tuple[int, int, float]] = []
    for h0, h1 in _horizontal_bands(lines):
        block = lines[h0:h1]
        if len(block) < _COLUMN_MIN_LINES:
            continue
        block_words = [w for l in block for w in l]
        gx = _best_gutter(block, block_words)
        if gx is None:
            continue

        runs: List[Tuple[int, int]] = []
        start = 0
        for i, line in enumerate(block):
            if _left_right(line, gx)[2]:                   # a straddling line ends the run
                if i - start >= _COLUMN_MIN_LINES:
                    runs.append((start, i))
                start = i + 1
        if len(block) - start >= _COLUMN_MIN_LINES:
            runs.append((start, len(block)))

        for s, e in runs:
            band = block[s:e]
            both = [l for l in band if all(_left_right(l, gx)[:2])]
            if len(both) < _COLUMN_MIN_BOTH:
                continue
            left_cells = [" ".join(w["text"] for w in _left_right(l, gx)[0]) for l in band]
            left_cells = [c for c in left_cells if c.strip()]
            right_cells = [" ".join(w["text"] for w in _left_right(l, gx)[1]) for l in band]
            right_cells = [c for c in right_cells if c.strip()]
            if not left_cells:
                continue
            tails = sum(1 for c in left_cells
                        if c.strip().endswith((",", ";", "--"))
                        or c.split()[-1].lower() in _PROSE_TAIL_WORDS) / len(left_cells)
            lower = _lower_fraction(left_cells)
            # Two-tier, exactly as `_is_running_prose` gates tables. The tail test
            # ALONE is not enough: `POLICY PERIOD: FROM 07/15/25 TO` ends in a
            # function word, and on page 85 that one line was enough to call a
            # boxed declarations header "prose" and split the date range in half.
            prose = lower > _ROW_LOWER_MAX or (lower > _ROW_LOWER_SOFT and tails > _ROW_TAIL_SOFT)
            # Real two-column prose runs LONG - measured on the client's package,
            # the median band is 38 lines and only 9 of 199 fall under 8. A blank
            # ACORD form's 4-line coincidental alignment (126 p5's fraud notice)
            # is not a column layout, and reordering it scrambles a paragraph.
            if prose and (e - s) >= _PROSE_MIN_LINES:
                out.append((h0 + s, h0 + e, gx))
                continue
            # Not prose. It may still CONTAIN two side-by-side identity blocks
            # (`Named Insured` over its address, `Producer` over its own) sitting
            # above a label/value table that must not move. Take only that region.
            region = _parallel_region(band, gx)
            if region:
                rs, re_ = region
                out.append((h0 + s + rs, h0 + s + re_, gx))
    return out


def _parallel_region(band: Sequence[Sequence[Word]], gx: float) -> Optional[Tuple[int, int]]:
    """``(start, end)`` of the two-parallel-blocks region inside ``band``, or None.

    ANCHORED on the header line - the first row carrying a short label in BOTH
    columns (`Named Insured | Producer`). Anchoring matters: page 1 of the client's
    package opens with five single-column lines (account number, policy term,
    `Common Declarations`) above the identity block, and taking a plain prefix
    dragged them into the middle of the insured's address.

    Ends at the first row whose RIGHT cell is an amount - that is a label/value
    table row (`Each Occurrence Limit | $1,000,000`), and reordering from there
    would orphan every figure from its label.
    """
    def cells(line):
        l, r, _ = _left_right(line, gx)
        return " ".join(w["text"] for w in l), " ".join(w["text"] for w in r)

    def substantial(text: str) -> bool:
        """Real content, not rule-off art. A teletype declarations page draws
        `*------------------------*` and `- - - - -` between its boxes; those
        split across any gutter and made page 85 anchor on box art, breaking
        `POLICY PERIOD: FROM 07/15/25 TO 07/15/26` in half."""
        return sum(1 for t in text.split() if any(c.isalnum() for c in t)) >= 2

    start = None
    for i, line in enumerate(band[:-1]):
        lt, rt = cells(line)
        if not (lt.strip() and rt.strip()):
            continue
        if _looks_like_value(lt) or _looks_like_value(rt):
            continue
        if len(lt.split()) > _PARALLEL_LABEL_MAX_WORDS or \
                len(rt.split()) > _PARALLEL_LABEL_MAX_WORDS:
            continue
        # The row under the header must carry real content in BOTH columns -
        # that is what makes this two parallel blocks rather than a coincidence.
        nlt, nrt = cells(band[i + 1])
        if substantial(nlt) and substantial(nrt):
            start = i
            break
    if start is None:
        return None

    end = start
    for i in range(start, len(band)):
        lt, rt = cells(band[i])
        if rt.strip() and _looks_like_value(rt):
            break
        if not (lt.strip() or rt.strip()):
            break
        end = i + 1
    # Drop trailing single-column lines so a heading below the block
    # ("Limits of Insurance") is never dragged into it - unless they belong to
    # the RIGHT column, which is where a producer's phone numbers sit.
    while end > start and not all(_left_right(band[end - 1], gx)[:2]):
        if _left_right(band[end - 1], gx)[1]:
            break
        end -= 1
    if end - start < _PARALLEL_MIN_LINES:
        return None
    head = band[start:end]
    # The region must carry real content SIDE BY SIDE on at least three rows.
    # Two address blocks do; a teletype box rule (`*---*` opposite a heading)
    # does not, and without this page 85 split `POLICY PERIOD: FROM 07/15/25 TO
    # 07/15/26` down the middle of its own date range.
    paired = sum(1 for l in head
                 if substantial(cells(l)[0]) and substantial(cells(l)[1]))
    if paired < _PARALLEL_MIN_PAIRED:
        return None
    # An identity block is short lines - a company name, a street, a city/state/zip.
    # A blank ACORD form's label grid is the same geometry with long cells
    # ("1. WITH THE EXCEPTION OF ANY ENCUMBRANCES, ARE ANY VEHICLES..."), and
    # splitting THOSE separates a printed label from the box it belongs to on
    # every filled application a broker uploads. Measured: ACORD 125 p2/p3,
    # 126 p3/p5, 127 p1/p2, 130 p1/p2 and 140 p1 all fail here; pages 1, 85 and
    # 205 of the client's package all pass with room to spare (max cell 31).
    for line in head:
        lt, rt = cells(line)
        if len(lt.strip()) > _PARALLEL_MAX_CELL_CHARS or \
                len(rt.strip()) > _PARALLEL_MAX_CELL_CHARS:
            return None
    left_cells = [c for c in (cells(l)[0] for l in head) if c.strip()]
    right_cells = [c for c in (cells(l)[1] for l in head) if c.strip()]
    # BOTH columns must contain a postal line. This feature exists for exactly one
    # shape - two mailing blocks side by side, `Named Insured` over its address and
    # `Producer` over its own - and the address is what proves it. Without this,
    # ACORD 127 p2's `DESCRIPTION OF GARAGE / STORAGE LOCATIONS | MAXIMUM DOLLAR
    # VALUE SUBJECT TO LOSS` label grid passed every other gate and was split.
    if not (any(_has_postal(c) for c in left_cells)
            and any(_has_postal(c) for c in right_cells)):
        return None
    if not _is_parallel_blocks(left_cells, right_cells):
        return None
    return start, end


_POSTAL_RE = None


def _has_postal(text: str) -> bool:
    """A US city/state/ZIP line - `DENVER, CO 80216-3121`, `ENGLEWOOD CO 80112`."""
    global _POSTAL_RE
    if _POSTAL_RE is None:
        import re
        _POSTAL_RE = re.compile(r"\b[A-Z]{2}\.?\s+\d{5}(-\d{4})?\b", re.I)
    return bool(_POSTAL_RE.search(text))


_VALUE_RE = None


def _looks_like_value(text: str) -> bool:
    """A cell that is an AMOUNT or a bare figure, not a name or a label.

    The test that keeps `Each Occurrence Limit | $1,000,000` intact. Deliberately
    narrow: currency, a bare number, or a number with a short parenthetical
    qualifier as ACORD prints it (`$500,000(any one premises)`).
    """
    global _VALUE_RE
    if _VALUE_RE is None:
        import re
        _VALUE_RE = re.compile(
            r"^[\$\(]?\s*[\d][\d,.\s/-]*%?\s*\)?(\s*\([^)]{0,40}\))?[.\s]*$"
        )
    return bool(_VALUE_RE.match(text.strip()))


def _is_parallel_blocks(left: Sequence[str], right: Sequence[str]) -> bool:
    """Two side-by-side blocks that each read DOWN - `Named Insured` over its own
    address, `Producer` over its own.

    This is the client-reported "producer details stamped on the insured" defect
    at its source (pages 1, 125 and 205 of the package). It is NOT prose, so the
    prose gate holds it back, and it is geometrically identical to the limits
    table three lines below it on the same page - which reordering would destroy.

    Two conditions, both required:
      * the band OPENS with a label in each column - neither cell is a value and
        neither is long enough to be a sentence; and
      * the right column is not a column of AMOUNTS. `Each Occurrence Limit |
        $1,000,000` fails here even when its first row somehow reads as a label.
    """
    if len(left) < _PARALLEL_MIN_LINES or len(right) < _PARALLEL_MIN_LINES:
        return False
    head_l, head_r = left[0].strip(), right[0].strip()
    if not head_l or not head_r:
        return False
    if _looks_like_value(head_l) or _looks_like_value(head_r):
        return False
    if len(head_l.split()) > _PARALLEL_LABEL_MAX_WORDS or \
            len(head_r.split()) > _PARALLEL_LABEL_MAX_WORDS:
        return False
    # A right column that CARRIES AMOUNTS is a label/value table, whatever else
    # it says. `COVERED AUTOS LIABILITY 01 | $ 1,000,000 .$ 1,496.00` on page 85
    # is a coverage-and-premium schedule; reordering it orphans every premium
    # from its coverage. `_looks_like_value` alone missed it - the cell holds two
    # amounts and prose - so this asks whether an amount appears ANYWHERE in it.
    monied = sum(1 for c in right if _has_amount(c)) / len(right)
    if monied > _PARALLEL_MAX_VALUE_FRAC:
        return False
    values = sum(1 for c in right if _looks_like_value(c)) / len(right)
    return values <= _PARALLEL_MAX_VALUE_FRAC


_AMOUNT_RE = None


def _has_amount(text: str) -> bool:
    """A currency figure anywhere in the cell - `$1,496.00`, `$ 5,000`, `1,198.00`."""
    global _AMOUNT_RE
    if _AMOUNT_RE is None:
        import re
        _AMOUNT_RE = re.compile(r"\$\s*\d|\b\d{1,3}(,\d{3})+(\.\d+)?\b|\b\d+\.\d{2}\b")
    return bool(_AMOUNT_RE.search(text))


def _emit_lines(words: Sequence[Word]) -> List[str]:
    """Lines of a page with every prose column band read down its own column.

    Character-preserving: a band's words are re-grouped, never dropped or altered,
    which `test_column_reorder_loses_no_characters` pins.
    """
    lines = _cluster_lines(words)
    bands = column_bands(words)
    if not bands:
        return [_line_text(l) for l in lines]
    out: List[str] = []
    i = 0
    by_start = {s: (e, gx) for s, e, gx in bands}
    while i < len(lines):
        if i in by_start:
            e, gx = by_start[i]
            left: List[str] = []
            right: List[str] = []
            for line in lines[i:e]:
                l, r, _ = _left_right(line, gx)
                if l:
                    left.append(_line_text(l))
                if r:
                    right.append(_line_text(r))
            out.extend(left)
            out.extend(right)
            i = e
        else:
            out.append(_line_text(lines[i]))
            i += 1
    return out


def page_text(page, pw: Optional[Tuple[List[Word], int]] = None) -> Tuple[str, int]:
    """``page.extract_text()`` unless a line was repaired; then the page rebuilt
    from ``page_words`` - lines in top order, words joined by one space, which is
    ``extract_text()``'s own join (identity pinned by test on the whole corpus).
    ``pw`` lets a caller that already ran ``page_words`` pass its result in.

    Two transforms can change a page: the riffle repair, and reading two columns of
    prose down their own column instead of straight across (``column_bands``). If
    neither applies the pdfplumber text is returned untouched."""
    words, repaired = pw if pw is not None else page_words(page)
    if not words:
        return (page.extract_text() or ""), repaired
    try:
        bands = column_bands(words)
    except Exception as ex:                              # noqa: BLE001 - never cost a page its text
        logger.debug("page_layout: column scan failed: %s", ex)
        bands = []
    if not repaired and not bands:
        return (page.extract_text() or ""), 0
    return "\n".join(_emit_lines(words)), repaired


# ─────────────────────────────────────────────────────────────────────────────
# 2. Header-anchored tables
# ─────────────────────────────────────────────────────────────────────────────

def _median_height(words: Sequence[Word]) -> float:
    hs = [w["bottom"] - w["top"] for w in words if w["bottom"] > w["top"]]
    return statistics.median(hs) if hs else 0.0


def _cells(line: Sequence[Word], gap: float,
           anchors: Sequence[float] = (), anchor_tol: float = 0.0) -> List[Dict[str, Any]]:
    """Split an x-sorted line into cells.

    A new cell starts at a gap wider than ``gap`` - or, for body lines, at a word
    whose left edge sits ON a header column anchor (within ``anchor_tol``). The
    second rule is what separates a value from a cell that overruns into its
    column: on the loss run the description ends at x=384 and ``$4,850`` is drawn
    at the PAID anchor x=360, so there is no gap between them at all. A word that
    merely overflows into a column starts at an arbitrary x, never on the anchor,
    so it stays with its own cell.
    """
    groups: List[List[Word]] = [[line[0]]]
    for prev, w in zip(line, line[1:]):
        on_anchor = any(abs(w["x0"] - a) <= anchor_tol for a in anchors) if anchors else False
        if w["x0"] - prev["x1"] > gap or on_anchor:
            groups.append([w])
        else:
            groups[-1].append(w)
    return [{"x0": g[0]["x0"], "x1": g[-1]["x1"], "text": _line_text(g)} for g in groups]


def _is_label_line(cells: Sequence[Dict[str, Any]]) -> bool:
    """``Total Incurred: $17,150`` - a summary or label:value line, never a row.
    Judged on the gap-split first cell, so the rule holds whether the value was
    drawn in the same string as the label or in its own column."""
    return any(tok.endswith(":") for tok in cells[0]["text"].split())


def _starts_lower(text: str) -> bool:
    """A cell that begins mid-sentence. Records begin with a capital, a digit or a
    marker ("1.", "(c)", "*CL0100", "$"); running prose does not."""
    t = text.strip()
    return bool(t) and t[0].islower()


def _lower_fraction(cells: Sequence[str]) -> float:
    real = [c for c in cells if c.strip()]
    if not real:
        return 0.0
    return sum(1 for c in real if _starts_lower(c)) / len(real)


def _is_header(cells: Sequence[Dict[str, Any]]) -> bool:
    if len(cells) < _MIN_HEADER_CELLS:
        return False
    if any(c["text"].rstrip().endswith(":") for c in cells):
        return False                       # "Label: value" lines are not headers
    lettered = sum(1 for c in cells if any(ch.isalpha() for ch in c["text"]))
    if lettered < 2:                       # a row of bare numbers is data, not a header
        return False
    # A header names columns, so its cells are LABELS. A line of running prose in a
    # two-column policy form splits into the same shape ("transported | by | the |
    # "insured"") and is geometrically indistinguishable - measured on the client's
    # 271-page package, prose columns score a PERFECT 1.00 anchor occupancy, so no
    # geometric test can separate them. What separates them is that a label does not
    # begin mid-sentence. Measured: 0.00 lowercase-start on all 40 genuine headers in
    # the corpus (client package, ACORD templates, Word tables, real policy
    # schedules) against a median 0.83 on policy wording.
    return _lower_fraction([c["text"] for c in cells]) <= _HEADER_LOWER_MAX


def _column_of(x0: float, cols: Sequence[float], tol: float) -> int:
    """Right-most column whose left edge is at or before this cell's left edge."""
    col = 0
    for i, cx in enumerate(cols):
        if cx <= x0 + tol:
            col = i
    return col


def _looks_like_heading(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters or len(text) > _SECTION_MAX_LEN or text.rstrip().endswith("-"):
        return False                       # "PRO-" is a hyphenated fragment, not a heading
    upper = sum(1 for ch in letters if ch.isupper())
    return upper / len(letters) >= 0.7


# Words that can only ever be a sentence fragment, never a cell on their own.
# DELIBERATELY NARROWER than _PROSE_TAIL_WORDS: an ACORD schedule legitimately
# prints `Other`, `Any`, `Not` and `This` as whole cells - page 1 of the client's
# package lost its entire coverage-and-premium grid to the row `8 | Other`.
_BARE_CONNECTIVES = frozenset("""
and or of the to a in by for that with is are be as on at from than nor but
""".split())

_PROSE_TAIL_WORDS = frozenset("""
and or of the to a in by for that with is are be as on at from not any it this which
than but nor if when while such other than under over into upon
""".split())


def _is_running_prose(rows: Sequence[Sequence[str]]) -> bool:
    """Body rows that are sentence fragments rather than records.

    Second gate, after `_is_header`'s. A policy form's two columns of legal wording
    are a real grid geometrically - the columns exist - so the only thing that says
    "this is prose" is the text. Two tells, both measured across every table in the
    corpus (40 genuine, 48 policy-wording):

      * a ROW that begins mid-sentence (`ten days before the cancellation...`).
        Genuine tables: 0.00 median, 0.40 max (one Word table). Prose: 0.67 median.
      * a CELL that ends where a sentence continues - a comma, a semicolon, or a
        function word. Genuine: 0.00 median. Prose: 0.41 median.

    Either alone would cost a real table (a wrapped description legitimately ends
    in a conjunction), so the weaker thresholds are required together.
    """
    firsts = [r[0] for r in rows if r and r[0].strip()]
    if not firsts:
        return False
    first_lower = _lower_fraction(firsts)
    cells = [c.strip() for r in rows for c in r if c.strip()]
    tails = sum(1 for c in cells
                if c.endswith((",", ";", "--")) or c.split()[-1].lower() in _PROSE_TAIL_WORDS)
    tail_frac = tails / max(1, len(cells))
    return (first_lower > _ROW_LOWER_MAX
            or (first_lower > _ROW_LOWER_SOFT and tail_frac > _ROW_TAIL_SOFT))


def _is_letter_soup(header: Sequence[str], rows: Sequence[Sequence[str]]) -> bool:
    """Reject a "table" whose words are mostly single letters.

    On dense ACORD forms pdfplumber's own ``extract_words`` merges two stacked 6pt
    box labels into one line and riffles them into ``C C O HE V C E K RAGES``. That
    soup is already in the page text today (this module changes nothing there);
    the point is not to echo it a second time dressed as structured data. A real
    table's alphabetic tokens are words: measured 0 single-letter tokens across
    every genuine table in the corpus, against 60-90% in the soup.
    """
    cells = [c.strip() for c in list(header) + [c for r in rows for c in r] if c.strip()]
    # A real table cell is never the word "and". One bare function word standing
    # as a whole cell means a sentence was cut at a column boundary - two of the
    # 21 tables on the client's package (pages 117 and 252) survived every other
    # gate on this alone, because their fragments happen to be capitalised.
    if any(c.lower().strip(".,;:") in _BARE_CONNECTIVES for c in cells):
        return True
    tokens = [t for cell in cells
              for t in cell.split() if any(ch.isalpha() for ch in t)]
    if len(tokens) < 4:
        return False
    single = sum(1 for t in tokens if len(t) == 1)
    return single / len(tokens) > _SOUP_RATIO


def detect_tables(words: Sequence[Word]) -> List[Dict[str, Any]]:
    """Header-anchored tables on one page. Returns a list of
    ``{"section", "header", "rows", "top", "bottom"}``; empty when none qualify."""
    if not _TABLES_ON or len(words) < 6:
        return []
    h = _median_height(words)
    if h <= 0:
        return []
    gap = _CELL_GAP_RATIO * h
    tol = _ALIGN_TOL_RATIO * h
    anchor_tol = _ANCHOR_TOL_RATIO * h

    lines = _cluster_lines(words)
    cell_lines = [_cells(line, gap) for line in lines]
    tables: List[Dict[str, Any]] = []
    i = 0
    while i < len(lines):
        header = cell_lines[i]
        if not _is_header(header):
            i += 1
            continue
        cols = [c["x0"] for c in header]
        ncols = len(cols)
        rows: List[List[str]] = []
        aligned_rows = 0
        j = i + 1
        while j < len(lines):
            if _is_label_line(cell_lines[j]):
                break                                   # summary / key:value line
            cells = _cells(lines[j], gap, cols, anchor_tol)
            mapped = [(_column_of(c["x0"], cols, tol), c) for c in cells]
            first_col = mapped[0][0]
            distinct = len({col for col, _ in mapped})
            if first_col == 0:
                if distinct < 2:
                    break                               # a heading or a paragraph line
                row = [""] * ncols
                for col, c in mapped:
                    row[col] = (row[col] + " " + c["text"]).strip() if row[col] else c["text"]
                rows.append(row)
                if sum(1 for col, c in mapped if abs(c["x0"] - cols[col]) <= tol) >= 2:
                    aligned_rows += 1
            else:
                if not rows:
                    break
                for col, c in mapped:                   # wrapped continuation
                    if not rows[-1][col]:
                        rows[-1][col] = c["text"]
                        continue
                    # "; " separates two STACKED VALUES (a certificate prints
                    # `Each Occurrence $1,000,000` over `General Aggregate
                    # $2,000,000` in one cell). A description that merely WRAPPED
                    # is one value, and a semicolon inside it invents a break
                    # that is not in the document - `Confidential Or Personal;
                    # Material Or Information` on page 207.
                    sep = "; " if _has_amount(c["text"]) else " "
                    rows[-1][col] = rows[-1][col] + sep + c["text"]
            j += 1

        accept = (len(rows) >= 2 or (len(rows) >= 1 and ncols >= 4)) \
            and aligned_rows >= _MIN_ALIGNED_ROWS * len(rows) \
            and not _is_letter_soup([c["text"] for c in header], rows) \
            and not _is_running_prose(rows)
        if not accept:
            i += 1
            continue

        section: Optional[str] = None
        for k in range(i - 1, max(-1, i - 1 - _SECTION_LOOKBACK), -1):
            if len(cell_lines[k]) == 1 and _looks_like_heading(cell_lines[k][0]["text"]):
                section = cell_lines[k][0]["text"]
                break

        tables.append({
            "section": section,
            "header": [c["text"] for c in header],
            "rows": rows,
            "top": min(w["top"] for w in lines[i]),
            "bottom": max(w["bottom"] for w in lines[j - 1]),
        })
        i = j
    return tables


def render_tables(tables: Sequence[Dict[str, Any]], page_no: int) -> str:
    """One single-newline block per table (clean_text-safe: no blank lines).
    Every cell is a verbatim join of printed words, so downstream verbatim
    verification (``_verify_dec_entries``) still finds each label and value."""
    blocks: List[str] = []
    for t in tables:
        section = f" - {t['section']}" if t.get("section") else ""
        lines = [TABLE_OPEN.format(page=page_no, section=section),
                 " | ".join(t["header"])]
        lines.extend(" | ".join(row) for row in t["rows"])
        lines.append(TABLE_CLOSE)
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


# ─────────────────────────────────────────────────────────────────────────────
# Google Vision adapter - word boxes from a fullTextAnnotation, so scanned pages
# run the same table detector. Coordinates are pixels; every threshold above is
# relative to word height, so nothing needs converting.
# ─────────────────────────────────────────────────────────────────────────────

def vision_words(annotation: Any) -> List[Word]:
    """Words from a Vision ``fullTextAnnotation`` (REST dict or gRPC proto).
    Never raises - geometry is a bonus on top of the text, never a dependency."""
    out: List[Word] = []
    try:
        pages = annotation.get("pages") if isinstance(annotation, dict) else getattr(annotation, "pages", None)
        for page in pages or []:
            blocks = page.get("blocks") if isinstance(page, dict) else page.blocks
            for block in blocks or []:
                paras = block.get("paragraphs") if isinstance(block, dict) else block.paragraphs
                for para in paras or []:
                    words = para.get("words") if isinstance(para, dict) else para.words
                    for word in words or []:
                        syms = word.get("symbols") if isinstance(word, dict) else word.symbols
                        text = "".join(
                            (s.get("text", "") if isinstance(s, dict) else s.text) for s in syms or []
                        )
                        if not text.strip():
                            continue
                        box = word.get("boundingBox") if isinstance(word, dict) else word.bounding_box
                        verts = box.get("vertices") if isinstance(box, dict) else getattr(box, "vertices", None)
                        xs, ys = [], []
                        for v in verts or []:
                            xs.append(float(v.get("x", 0) if isinstance(v, dict) else v.x))
                            ys.append(float(v.get("y", 0) if isinstance(v, dict) else v.y))
                        if len(xs) < 2:
                            continue
                        out.append({"x0": min(xs), "x1": max(xs), "top": min(ys),
                                    "bottom": max(ys), "text": text})
    except Exception as ex:                              # noqa: BLE001
        logger.debug("page_layout: vision word geometry unavailable: %s", ex)
        return []
    return out
