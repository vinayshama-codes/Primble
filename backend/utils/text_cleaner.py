import re
import os
import hashlib
import logging

logger = logging.getLogger(__name__)

# ── Paragraph de-duplication ─────────────────────────────────────────────────
# DEFAULT OFF. This used to MD5-hash every paragraph across the whole document
# and drop every repeat, which silently deleted real data: a three-vehicle fleet
# garaged at one address has that address three times, and only the first
# survived. Measured on a realistic fixture, three garaging lines collapsed to
# one.
#
# What it was for is page furniture — a running header repeated on all 271 pages.
# On a real package that is ~16k chars out of ~670k, i.e. **2.4%**, and with
# prefix caching running at 99% those tokens bill at a tenth of list price. The
# saving is noise; the data loss is not.
#
# If you re-enable it, it now requires a paragraph to repeat at least this many
# times AND be short, so a running header still goes and a fleet row still stays.
# Set TEXT_DEDUP_MIN_REPEATS=5 (or higher) to turn it on.
_DEDUP_MIN_REPEATS = int(os.getenv("TEXT_DEDUP_MIN_REPEATS", "0"))
_DEDUP_MAX_LEN     = int(os.getenv("TEXT_DEDUP_MAX_LEN", "120"))


def clean_text(text: str) -> str:
    """Pre-LLM text cleaning. **Removes page furniture only — never content.**

    READ THIS BEFORE ADDING A FILTER HERE. This function runs on EVERY uploaded
    document before extraction, before gap fill, before anything. Whatever it
    deletes is invisible to the entire rest of the pipeline, including
    `_verify_coverage`, which measures 100% coverage of *what survives this
    function* and will happily report success over a shredded document.

    Three filters were removed on 2026-07-30 after they were measured deleting
    56% of a realistic declarations page:

    1. **ALL-CAPS "boilerplate" filter** — dropped any line of >8 words that was
       >80% uppercase. Declarations pages are written in capitals. It deleted the
       named insured, both General Liability limits, and a vehicle schedule row.
       Whether a given line survived depended on how many of its tokens were pure
       digits (which are not `.isupper()`), so a mailing address with three
       numeric tokens scored 70% and lived while the line above it scored 100%
       and died. Arbitrary, invisible, and unlogged. There is no defensible
       version of this filter in this domain.
    2. **Bare-digit line removal** — `^\\s*\\d+\\s*$` deleted a postcode, limit,
       year, class code or premium sitting alone in a table cell.
    3. **10-character paragraph floor** — deleted short real values ("CO 80216",
       "$1,000,000", "07/15/25").

    What remains is genuinely furniture: "Page 3 of 12" and "- 3 -" markers.
    """
    text = text or ""              # defensive: never crash a whole upload on a None
    original_len = len(text)
    # Loss is measured on NON-WHITESPACE characters only.
    #
    # The naive `len(in) - len(out)` counts the whitespace collapse below as
    # deleted content. pdfplumber pads columns with runs of spaces, so a perfectly
    # intact layout-extracted declarations page reports ~22% "removed" and trips
    # the alarm — measured. An alarm that fires on the normal case gets ignored,
    # and then it is not believed on the day it is real, which is precisely how a
    # 56% content deletion survived several rounds of cost and coverage review.
    original_ink = _ink(text)

    try:
        import ftfy
        text = ftfy.fix_text(text)
    except ImportError:
        pass  # ftfy optional

    # Page markers only. NOTE the bare-digit rule that used to live here is gone
    # on purpose — a lone number on a line is far more often a real value in an
    # ACORD table than it is a page number, and "Page N of M" / "- N -" already
    # cover the actual page furniture.
    text = re.sub(r'\bPage\s+\d+\s+of\s+\d+\b', '', text, flags=re.I)
    text = re.sub(r'^\s*-\s*\d+\s*-\s*$', '', text, flags=re.M)

    # Collapse whitespace (safe — changes spacing, never drops a token)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)

    paragraphs = [p.strip() for p in text.split('\n\n')]
    paragraphs = [p for p in paragraphs if p]          # drop only truly empty

    dropped_dupes = 0
    if _DEDUP_MIN_REPEATS > 0:
        counts: dict = {}
        for p in paragraphs:
            if len(p) <= _DEDUP_MAX_LEN:
                counts[p] = counts.get(p, 0) + 1
        furniture = {p for p, n in counts.items() if n >= _DEDUP_MIN_REPEATS}
        seen: set = set()
        kept = []
        for p in paragraphs:
            if p in furniture:
                h = hashlib.md5(p.encode(), usedforsecurity=False).hexdigest()
                if h in seen:
                    dropped_dupes += 1
                    continue
                seen.add(h)
            kept.append(p)
        paragraphs = kept

    out = '\n\n'.join(paragraphs)

    # Always account for what this function removed. It was previously silent,
    # which is how a 56% content deletion went unnoticed through several rounds
    # of cost and coverage work.
    out_ink   = _ink(out)
    ink_lost  = original_ink - out_ink
    ws_lost   = (original_len - len(out)) - ink_lost
    if original_len:
        logger.info(
            "clean_text: in=%d out=%d | content_chars %d -> %d (lost %d, %.2f%%) "
            "| whitespace_collapsed=%d dupes_dropped=%d",
            original_len, len(out), original_ink, out_ink, ink_lost,
            (100.0 * ink_lost / original_ink) if original_ink else 0.0,
            ws_lost, dropped_dupes,
        )
        # Threshold applies to CONTENT only, and is tight on purpose: what remains
        # in this function is page furniture ("Page 3 of 12", "- 3 -"), which is a
        # fraction of a percent of any real submission. Anything approaching 2% of
        # the non-whitespace characters means a filter is eating data.
        if original_ink and ink_lost > original_ink * 0.02:
            logger.warning(
                "clean_text: removed %.2f%% of the document's CONTENT characters "
                "(%d of %d, excluding whitespace). Page furniture cannot account for "
                "that — a filter is deleting data. Inspect before trusting the fill.",
                100.0 * ink_lost / original_ink, ink_lost, original_ink,
            )
    return out


_WS_RE = re.compile(r"\s+")


def _ink(s: str) -> int:
    """Count of non-whitespace characters — the only thing that can be 'lost'.

    Collapsing two spaces to one, or three newlines to two, changes `len()` but
    cannot lose a token. Measuring loss in raw length conflates the two and makes
    the alarm useless on layout-extracted PDFs. See the note in `clean_text`.
    """
    return len(_WS_RE.sub("", s or ""))


def table_rows_to_text(tables: list) -> str:
    """Convert extracted table list to LLM-readable text block."""
    if not tables:
        return ""
    parts = []
    for tbl in tables:
        page = tbl.get("page", "?")
        rows = tbl.get("rows", [])
        if not rows:
            continue
        header = " | ".join(str(c) for c in (rows[0] or []))
        body = "\n".join(" | ".join(str(c or "") for c in row) for row in rows[1:])
        parts.append(f"[TABLE page={page}]\n{header}\n{body}\n[/TABLE]")
    return "\n\n".join(parts)
